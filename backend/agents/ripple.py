"""Ripple: a late alert arrives after an investigation. Re-do only the findings the new alert can change.

Rules (plain, and printed in the events so nothing is hidden):
  1. Re-rank with the full alert set. Existing hypotheses keep their findings and get a new score/rank.
  2. A candidate whose ranking now enters the top 3 and has no hypothesis yet gets a new hypothesis and a full set of specialists.
  3. A finding is STALE if its receipt read one of the new alerting services, or if it is an Impact finding (it says whether
     "every alert is inside the blast radius") on a hypothesis whose explained-alert set changed.
     Changes, History and People findings do not depend on the alert set, so they are kept, not re-run.
  4. Stale findings are retired (kept in the graph as SUPERSEDED_FOR, off the live board). Only the specialists that lost a finding re-run,
     only for the hypotheses affected. Then the Lead decides again; the old verdict is kept as PREVIOUSLY_CONCLUDED.
"""
import json
import time

from backend.agents.board import Session
from backend.agents.runner import TOP_K, RulePolicy, _first_alert_ts, conclude
from backend.tools.base import rows


def ripple(graph, prev, late_alerting, now=None, policy=None, emit=None):
    """`prev` is the dict returned by run_investigation. Returns the new result, plus `ripple` stats."""
    t0 = time.time()
    now = int(now if now is not None else time.time())
    policy = policy or RulePolicy()
    inv = prev["investigation"]
    old = set(prev["alerting"])
    new = sorted(set(late_alerting) - old)
    events = []

    def push(agent, text, kind="step", **extra):
        e = dict(type=kind, agent=agent, text=text, t=round(time.time() - t0, 2), ripple=True, **extra)
        events.append(e)
        if emit:
            emit(e)

    if not new:
        push("Lead", "Ripple: no new alerting services, nothing to redo", kind="notice")
        return dict(prev, ripple=dict(new_alerts=[], retired=0, kept=0, reran=[]))

    alerting = sorted(old | set(new))
    graph.query("""MATCH (i:Investigation {id:$i}) UNWIND $a AS n MATCH (x:Alert)-[:ON]->(:Service {name:n}) WHERE x.ts <= $now
                   MERGE (i)-[:TRIGGERED_BY]->(x)""", {"i": inv, "a": new, "now": now})
    s = Session(graph, inv, alerting)
    s._n = max([int(r[0].rsplit("-", 1)[1]) for r in rows(graph, "MATCH (f:Finding) WHERE f.id STARTS WITH $p RETURN f.id", {"p": f"f-{inv}-"})] or [0])
    push("Lead", f"Ripple: {len(new)} late alert(s) on {', '.join(new)}; re-ranking with {len(alerting)} alerting services", kind="start", investigation=inv)

    before = s.call("Lead", "rank_root_causes", {"alerting": sorted(old), "top_k": 40}).data["candidates"]
    rr = s.call("Lead", "rank_root_causes", {"alerting": alerting, "top_k": 40})
    after = rr.data["candidates"]
    ctx = dict(alerting=alerting, n_alerting=len(alerting), now=now, first_alert_ts=_first_alert_ts(graph, alerting, now))
    ctx["ranking"] = dict(rr.data, candidates=after[:5])
    old_expl = {c["candidate"]: set(c["explains"]) for c in before}
    new_expl = {c["candidate"]: set(c["explains"]) for c in after}
    rank_of = {c["candidate"]: c for c in after}

    by_service = {h["service"]: dict(h) for h in prev["hypotheses"]}
    # 1+2: refresh existing hypotheses, add newcomers to the top 3
    for svc, h in by_service.items():
        c = rank_of.get(svc)
        if c:
            graph.query("MATCH (:Investigation {id:$i})-[:CONSIDERS]->(h:Hypothesis {id:$h}) SET h.rank=$r, h.structural_score=$s",
                        {"i": inv, "h": h["id"], "r": c["rank"], "s": c["score"]})
            h.update(rank=c["rank"], structural_score=c["score"], coverage=c["coverage"], precision=c["precision"], summary=c["summary"])
    newcomers = []
    for c in after[:TOP_K]:
        if c["candidate"] not in by_service:
            hid = f"h-{inv}-r{c['rank']}"
            graph.query("""MATCH (i:Investigation {id:$i}), (s:Service {name:$s})
                           CREATE (h:Hypothesis {id:$h, rank:$r, structural_score:$sc, status:'open'}), (i)-[:CONSIDERS]->(h), (h)-[:ABOUT]->(s)""",
                        {"i": inv, "s": c["candidate"], "h": hid, "r": c["rank"], "sc": c["score"]})
            h = dict(id=hid, service=c["candidate"], rank=c["rank"], structural_score=c["score"], coverage=c["coverage"], precision=c["precision"], summary=c["summary"])
            by_service[c["candidate"]] = h
            newcomers.append(h)
            push("Lead", f"New hypothesis {c['candidate']} (rank {c['rank']}) after the late alert", kind="step")

    # 3: which findings are stale?
    changed = {svc for svc in by_service if old_expl.get(svc) != new_expl.get(svc)}
    live = rows(graph, """MATCH (:Investigation {id:$i})-[:CONSIDERS]->(h:Hypothesis)<-[:SUPPORTS|WEAKENS]-(f:Finding)
                          RETURN f.id, f.kind, h.id, f.receipt""", {"i": inv})
    hid_to_svc = {h["id"]: svc for svc, h in by_service.items()}
    stale, kept = [], 0
    redo = {}                                           # agent -> set of hypothesis ids to redo
    agent_of = {"impact": "Impact", "temporal": "Changes", "historical": "History", "people": "People", "structural": "Lead"}
    for fid, kind, hid, receipt in live:
        try:
            read = set(json.loads(receipt or "{}").get("nodes_read", []))
        except ValueError:
            read = set()
        hit_new = any(f"Service:{n}" in read for n in new)
        impact_changed = kind == "impact" and hid_to_svc.get(hid) in changed
        if hit_new or impact_changed:
            stale.append(fid)
            redo.setdefault(agent_of.get(kind, "Lead"), set()).add(hid)
        else:
            kept += 1
    s.supersede_findings(stale)
    for h in newcomers:                                 # newcomers have no findings: every specialist works on them
        for a in ("Impact", "Changes", "History", "People"):
            redo.setdefault(a, set()).add(h["id"])
    push("Lead", f"Ripple: {len(stale)} finding(s) retired as out of date, {kept} kept without re-running", kind="step")

    # 4: re-run only the affected specialists on only the affected hypotheses
    hyps = sorted(by_service.values(), key=lambda h: h["rank"])
    top_ids = [h["id"] for h in hyps[:TOP_K]]
    reran = []
    for agent, fn in (("Impact", policy.impact), ("Changes", policy.changes), ("History", policy.history), ("People", policy.people)):
        targets = [h for h in hyps if h["id"] in redo.get(agent, set()) and h["id"] in top_ids]
        if agent == "People":
            targets = targets[:1] if targets and hyps[0]["id"] == targets[0]["id"] else ([hyps[0]] if hyps[0]["id"] in redo.get(agent, set()) else [])
        if targets:
            reran.append(agent)
            fn(s, targets, ctx, lambda a, t, kind="step", **x: push(a, t, kind, **x))
    board = s.read_board()
    push("Lead", "Read the updated board from the graph: " + "; ".join(f"{b['service']}: {len(b['findings'])} findings" for b in board))
    d = policy.decide(s, [h for h in hyps if h["id"] in top_ids], board, ctx, lambda a, t, kind="step", **x: push(a, t, kind, **x))
    result = conclude(graph, s, d, hyps, board, ctx, alerting, push, t0)
    result["ripple"] = dict(new_alerts=new, retired=len(stale), kept=kept, reran=reran, new_hypotheses=[h["service"] for h in newcomers])
    return result
