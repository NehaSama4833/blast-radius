"""Deterministic world generator. Same config + seed => byte-identical world.

All times are stored as `age_s` (seconds BEFORE "now"). The loader converts them to real timestamps
when the world is copied into a graph, so "deployed 41 minutes ago" is always true.
"""
import hashlib
import random

from backend.world import topology as topo

DAY = 86400
CHANGE_KINDS = ("code", "config", "infra")

CODE_SUMMARIES = [
    "Refactor {svc} request handling", "Upgrade {svc} dependencies", "Add caching to {svc} hot path",
    "Fix null handling in {svc}", "Release {svc} v{v}", "Tune {svc} timeouts and retries",
]
CONFIG_SUMMARIES = [
    "Change {svc} feature flags", "Adjust {svc} rate limits", "Update {svc} connection settings",
    "Raise {svc} log level", "Change {svc} pool sizes",
]
INFRA_SUMMARIES = [
    "Resize {svc} node pool", "Rotate {svc} credentials", "Upgrade {svc} base image", "Move {svc} to new subnet",
]


def deploy_summary(rng, kind, svc):
    pool = {"code": CODE_SUMMARIES, "config": CONFIG_SUMMARIES, "infra": INFRA_SUMMARIES}[kind]
    return rng.choice(pool).format(svc=svc, v=f"{rng.randint(1, 9)}.{rng.randint(0, 20)}.{rng.randint(0, 9)}")


def sha(rng):
    return "%08x" % rng.getrandbits(32)


def build_world(config):
    rng = random.Random(config["seed"])
    services = [
        dict(name=n, layer=l, tier=t, language=lang, monitored=m, team=team)
        for n, (l, t, lang, m, team) in config["services"].items()
    ]
    deps = [dict(src=a, dst=b, kind=k) for a, b, k in config["deps"]]
    teams = [dict(name=n, channel=c) for n, c in config["teams"].items()]
    people = [dict(name=n, handle=h, timezone=tz, team=t, on_call=oc) for n, h, tz, t, oc in config["people"]]
    features = [dict(name=n, services=list(s)) for n, s in config["features"].items()]
    plans = ["enterprise"] * 8 + ["pro"] * 10 + ["free"] * 7
    customers = []
    for i, name in enumerate(config["customers"]):
        plan = plans[i % len(plans)]
        arr = {"enterprise": rng.randint(300, 900) * 1000, "pro": rng.randint(40, 150) * 1000, "free": 0}[plan]
        feats = rng.sample([f["name"] for f in features], k=rng.randint(1, min(4, len(features))))
        customers.append(dict(name=name, plan=plan, arr=arr, features=sorted(feats)))
    world = dict(name=config["name"], seed=config["seed"], services=services, deps=deps, teams=teams,
                 people=people, features=features, customers=customers, runbooks=[], deploys=[],
                 incidents=[], lessons=[])
    assert topo.is_dag(world), "dependency graph must be acyclic"

    by_team = {}
    for p in people:
        by_team.setdefault(p["team"], []).append(p["handle"])
    svc_team = {s["name"]: s["team"] for s in services}

    for name in config["runbooks"]:
        world["runbooks"].append(dict(
            title=f"{name} recovery", service=name,
            steps=f"1. Check {name} dashboards. 2. Check the most recent deploy to {name}. "
                  f"3. Roll back or scale. 4. Confirm dependents recover. 5. Page the {svc_team[name]} on-call."))

    def new_deploy(service, age_s, kind, summary, diff=None, author=None):
        author = author or rng.choice(by_team[svc_team[service]])
        n = rng.randint(1, 3)
        commits = [dict(sha=sha(rng), message=summary if i == 0 else f"{rng.choice(['wip', 'fix', 'tweak'])}: {service} change")
                   for i in range(n)]
        d = dict(id=None, age_s=int(age_s), kind=kind, summary=summary, service=service, author=author,
                 diff=diff or f"--- a/{service}/{kind}\n+++ b/{service}/{kind}\n@@ {summary}", commits=commits)
        world["deploys"].append(d)
        return d

    # --- planted incidents first (so their deploys exist), spread over the last 90 days
    incidents = []

    def add_incident(root, deploy, title, summary, action, ttr, age_s, fix):
        affected = sorted([root] + [s for s in topo.sync_dependents(world, root)])
        responders = sorted({deploy["author"], rng.choice(by_team[svc_team[root]]), rng.choice(by_team[svc_team[root]])})
        incidents.append(dict(
            id=None, title=title, summary=summary, severity=rng.choice(["sev1", "sev2"]),
            age_s=age_s, ttr_min=ttr, root=root, deploy=deploy, affected=affected, action=action,
            resolution=f"{fix}. Resolved in {ttr} minutes.", responders=responders))

    for pat in config["patterns"]:
        ages = sorted(rng.sample(range(6, 88), pat["occurrences"]))
        for a in ages:
            age = a * DAY + rng.randint(0, DAY - 1)
            ttr = rng.randint(*pat["ttr"])
            d = new_deploy(pat["service"], age + rng.randint(25, 55) * 60, pat["kind"], pat["deploy"])
            add_incident(pat["service"], d, pat["title"], pat["summary"], pat["action"], ttr, age, pat["fix"])
    generic = config["generic_roots"]
    for i in range(config["n_generic_incidents"]):
        root = generic[i % len(generic)]
        kind = rng.choice(CHANGE_KINDS)
        action = {"code": "hotfix", "config": "rollback", "infra": "restart"}[kind]
        age = rng.randint(3, 88) * DAY + rng.randint(0, DAY - 1)
        d = new_deploy(root, age + rng.randint(25, 55) * 60, kind, deploy_summary(rng, kind, root))
        add_incident(root, d, f"{root} degraded after {kind} change",
                     f"A {kind} change to {root} degraded dependent services; errors and latency rose. "
                     f"Fixed by {'rolling back' if action != 'restart' else 'restarting'} {root}.",
                     action, rng.randint(7, 40), age, f"{action.capitalize()} {root}")

    # --- background deploys (no deploys in the last 3h: scenarios add their own, so tests are clean)
    n_bg = len(services) * config["deploys_per_service_90d"]
    for _ in range(n_bg):
        s = rng.choice(services)["name"]
        kind = rng.choices(CHANGE_KINDS, weights=[6, 3, 1])[0]
        new_deploy(s, rng.randint(3 * 3600, 90 * DAY), kind, deploy_summary(rng, kind, s))

    # --- stable ids: oldest deploy gets the lowest number
    world["deploys"].sort(key=lambda d: (-d["age_s"], d["service"], d["summary"], d["commits"][0]["sha"]))
    for i, d in enumerate(world["deploys"], start=1):
        d["id"] = f"d-{i}"
    incidents.sort(key=lambda x: -x["age_s"])
    for i, inc in enumerate(incidents, start=1):
        inc["id"] = f"INC-{100 + i}"
        inc["deploy_id"] = inc["deploy"]["id"]
        del inc["deploy"]
    world["incidents"] = incidents

    # --- lessons: one per planted pattern, learned from the most recent occurrence
    for pat in config["patterns"]:
        mine = [i for i in incidents if i["root"] == pat["service"] and i["title"] == pat["title"]]
        world["lessons"].append(dict(
            pattern=pat["title"], fix=pat["fix"], service=pat["service"], times_seen=len(mine),
            last_seen_age_s=min(i["age_s"] for i in mine),
            avg_ttr_min=round(sum(i["ttr_min"] for i in mine) / len(mine), 1),
            learned_from=mine[-1]["id"]))
    return world


def world_digest(world) -> str:
    import json
    return hashlib.sha256(json.dumps(world, sort_keys=True).encode()).hexdigest()[:16]
