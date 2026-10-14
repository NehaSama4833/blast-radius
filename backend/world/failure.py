"""The failure model: the ONE place that decides what breaks and what alerts.

Used by the chaos button, the benchmark generator and the tests. Pure Python over a world dict.
Times are `age_s` (seconds before "now").
"""
import random
from dataclasses import dataclass, field

from backend.world import topology as topo
from backend.world.history import CHANGE_KINDS, deploy_summary, sha

CHAOS_SUMMARIES = {
    "config": ["Change {svc} connection pool max_connections 200 -> 40", "Lower {svc} timeout and memory limits",
               "Update {svc} rate limit and retry config"],
    "code": ["Release {svc}: refactor request path", "Release {svc}: switch serializer", "Hotfix {svc}: change query plan"],
    "infra": ["Resize {svc} node pool", "Rotate {svc} certificate", "Migrate {svc} to new instance type"],
}


@dataclass
class Outcome:
    world: str
    roots: list
    change_kind: str
    deploys: list            # triggering deploys + distractors (dicts, same shape as world["deploys"])
    alerts: list             # dicts: id, service, age_s, signal, severity
    truth: dict = field(default_factory=dict)

    @property
    def alerting(self):
        return sorted({a["service"] for a in self.alerts})

    @property
    def lag_alerting(self):
        return sorted({a["service"] for a in self.alerts if a["signal"] == "lag"})

    @property
    def first_alert_age_s(self):
        return max(a["age_s"] for a in self.alerts)


def _team_member(world, service, rng):
    team = {s["name"]: s["team"] for s in world["services"]}[service]
    return rng.choice([p["handle"] for p in world["people"] if p["team"] == team])


def _next_deploy_id(world, extra):
    n = len(world["deploys"]) + len(extra)
    return f"d-{n + 1}"


def alerting_for(world, broken):
    """Which services WOULD alert if `broken` services failed (same rules as break_service, no noise).
    Returns {service: signal}. `world` only needs "services" and "deps"."""
    svcs = topo.svc_map(world)
    out = {}
    for b in broken:
        deps = topo.sync_dependents(world, b)
        if svcs[b]["monitored"]:
            out.setdefault(b, "error_rate")
        for n in deps:
            if svcs[n]["monitored"]:
                out.setdefault(n, "error_rate")
        for n in topo.async_dependents(world, b):
            if svcs[n]["monitored"] and n not in deps:
                out.setdefault(n, "lag")
    return out


def break_service(world, service, change_kind="config", noise=None, rng=None, _id_offset=0, _first_alert_age=None):
    """Break `service` and return an Outcome with the alerts that would fire and the ground truth.

    noise = dict(flaky=bool, missing=bool, distractors=int)
    """
    noise = noise or {}
    rng = rng or random.Random(0)
    assert change_kind in CHANGE_KINDS
    svcs = topo.svc_map(world)
    first_age = _first_alert_age if _first_alert_age is not None else rng.randint(4, 12) * 60
    deploy_age = first_age + rng.randint(20, 60) * 60            # 20-60 minutes before the first alert
    d = dict(id=f"d-{len(world['deploys']) + 1 + _id_offset}", age_s=deploy_age, kind=change_kind, service=service,
             summary=rng.choice(CHAOS_SUMMARIES[change_kind]).format(svc=service),
             author=_team_member(world, service, rng), triggering=True)
    d["diff"] = f"--- a/{service}/{change_kind}\n+++ b/{service}/{change_kind}\n@@ {d['summary']}"
    d["commits"] = [dict(sha=sha(rng), message=d["summary"])]

    dependents = topo.sync_dependents(world, service)           # name -> hops
    expected = []                                                # (service, delay_s, signal)
    if svcs[service]["monitored"]:
        expected.append((service, 0, "error_rate"))
    for name, hops in sorted(dependents.items()):
        if svcs[name]["monitored"]:
            expected.append((name, 20 * hops + rng.randint(0, 40), rng.choice(["error_rate", "latency", "saturation"])))
    for name in topo.async_dependents(world, service):           # delayed lag alerts, async consumers
        if svcs[name]["monitored"] and name not in dependents:
            expected.append((name, 300 + rng.randint(0, 300), "lag"))

    missing = None
    if noise.get("missing") and len(expected) >= 3:
        victims = [e for e in expected if e[0] != service]
        missing = rng.choice(victims)[0]
        expected = [e for e in expected if e[0] != missing]

    alerts = [dict(service=n, age_s=max(first_age - delay, 1), signal=sig,
                   severity="critical" if svcs[n]["tier"] == 1 else ("high" if svcs[n]["tier"] == 2 else "medium"))
              for n, delay, sig in expected]

    flaky = None
    if noise.get("flaky"):
        failing = set(dependents) | {service}
        pool = [s["name"] for s in world["services"] if s["monitored"] and s["name"] not in failing]
        flaky = rng.choice(pool)
        alerts.append(dict(service=flaky, age_s=rng.randint(60, 600), signal="latency", severity="low"))

    deploys = [d]
    for i in range(int(noise.get("distractors", 0))):
        near = sorted(set(dependents) | set(topo.sync_dependencies(world, service)))
        near = [n for n in near if n != service] or [s["name"] for s in world["services"] if s["name"] != service]
        tgt = rng.choice(near)
        kind = rng.choice(CHANGE_KINDS)
        deploys.append(dict(id=f"d-{len(world['deploys']) + 2 + _id_offset + i}", age_s=first_age + rng.randint(5, 90) * 60,
                            kind=kind, service=tgt, summary=deploy_summary(rng, kind, tgt),
                            author=_team_member(world, tgt, rng), distractor=True,
                            diff=f"--- a/{tgt}/{kind}\n+++ b/{tgt}/{kind}\n@@ routine change",
                            commits=[dict(sha=sha(rng), message="routine change")]))

    truth = dict(root_causes=[service], deploy_ids=[d["id"]],
                 impacted_services=sorted(set(dependents) | {service}),
                 impacted_features=topo.features_hit(world, set(dependents) | {service}),
                 missing_alert=missing, flaky_alert=flaky, silent_root=not svcs[service]["monitored"])
    return Outcome(world=world["name"], roots=[service], change_kind=change_kind, deploys=deploys, alerts=alerts, truth=truth)


def merge(world, outcomes):
    """Two simultaneous failures (the 'ambiguous' tier). Ground truth: more than one cause."""
    alerts, deploys, seen = [], [], set()
    for o in outcomes:
        deploys += o.deploys
        for a in o.alerts:
            if a["service"] in seen:
                continue
            seen.add(a["service"])
            alerts.append(a)
    roots = [r for o in outcomes for r in o.roots]
    truth = dict(root_causes=roots, deploy_ids=[i for o in outcomes for i in o.truth["deploy_ids"]],
                 impacted_services=sorted({s for o in outcomes for s in o.truth["impacted_services"]}),
                 impacted_features=sorted({f for o in outcomes for f in o.truth["impacted_features"]}),
                 missing_alert=None, flaky_alert=None, silent_root=all(o.truth["silent_root"] for o in outcomes),
                 multiple_causes=True)
    return Outcome(world=outcomes[0].world, roots=roots, change_kind=outcomes[0].change_kind, deploys=deploys,
                   alerts=alerts, truth=truth)


def finalize_alert_ids(outcome):
    for i, a in enumerate(sorted(outcome.alerts, key=lambda x: -x["age_s"]), start=1):
        a["id"] = f"a-{i}"
    return outcome


def apply_outcome(graph, outcome, now):
    """Write the triggering deploys and alerts into a graph."""
    from backend.world.loader import load_alerts, load_deploys

    finalize_alert_ids(outcome)
    load_deploys(graph, outcome.deploys, now)
    load_alerts(graph, outcome.alerts, now)
