"""Investigation runner: Lead triage -> four specialists in parallel -> Lead reads the board and decides.

The runner is policy-agnostic. `RulePolicy` (below) is a deterministic, no-LLM policy that makes exactly the tool
calls a careful engineer would; it lets the whole pipeline run and be tested without an API key, and doubles as the
"graph tools, no LLM" ablation. A Claude-backed policy (Day 2, needs the key) plugs into the same three methods.
"""
import time
from concurrent.futures import ThreadPoolExecutor

from backend.agents.board import AGENTS, BoardError, start_investigation

TOP_K = 3
STRONG_FIT = 0.85          # structural score considered a strong fit
ABSTAIN_BELOW = 0.7        # design doc: below 70% fit => "likely more than one cause"


class RulePolicy:
    name = "rules"

    # ---- specialists ----------------------------------------------------------------------------------------
    def impact(self, s, hyps, ctx, emit):
        for h in hyps:
            r = s.call("Impact", "blast_radius", {"service": h["service"]})
            emit("Impact", f"blast_radius({h['service']}): {len(r.data['failing_now'])} services failing, features {r.data['features']}, ARR at risk {r.data['arr_at_risk']:,}")
            covered = set(ctx["alerting"]) <= ({h["service"]} | {f["service"] for f in r.data["failing_now"]})
            feats = ", ".join(r.data["features"]) or "no features"
            text = (f"If {h['service']} failed: {len(r.data['failing_now'])} services fail now and {len(r.data['at_risk_async'])} are at risk soon (async); "
                    f"features hit: {feats}; {len(r.data['customers'])} customers, ARR at risk {r.data['arr_at_risk']:,}. "
                    + ("Every current alert is inside that blast radius." if covered else "Some current alerts are OUTSIDE that blast radius."))
            cites = [f"Service:{h['service']}"] + [f"Feature:{f}" for f in r.data["features"][:5]]
            s.add_finding("Impact", h["id"], text, covered, cites, weight=1.0)
            emit("Impact", ("supports " if covered else "weakens ") + h["service"], kind="finding")
            h["impact"] = dict(arr=r.data["arr_at_risk"], features=r.data["features"], customers=len(r.data["customers"]), at_risk=r.data["at_risk_async"],
                               failing=len(r.data["failing_now"]), by_plan=r.data["customers_by_plan"])

    def changes(self, s, hyps, ctx, emit):
        for h in hyps:
            r = s.call("Changes", "recent_changes", {"services": [h["service"]], "until_ts": ctx["first_alert_ts"], "window_minutes": 120})
            changes = r.data["changes"]
            own = [c for c in changes if c["service"] == h["service"]]
            emit("Changes", f"recent_changes({h['service']}): {len(changes)} deploys in the 2h before the first alert, {len(own)} on it directly")
            if own:
                c = own[0]
                s.call("Changes", "change_details", {"deploy_id": c["deploy_id"]})
                text = f"{c['kind']} deploy {c['deploy_id']} to {h['service']} ('{c['summary']}') shipped {c['minutes_before']} min before the first alert, by {c['author']}."
                s.add_finding("Changes", h["id"], text, True, [f"Deploy:{c['deploy_id']}", f"Service:{h['service']}"], weight=1.0)
                h["deploy"] = c
                emit("Changes", f"supports {h['service']}: {c['deploy_id']} ({c['kind']}) {c['minutes_before']} min before", kind="finding")
            else:
                text = f"No deploy to {h['service']} in the 2 hours before the first alert" + (f" ({len(changes)} on its dependencies)." if changes else ".")
                s.add_finding("Changes", h["id"], text, False, [f"Service:{h['service']}"], weight=1.0)
                emit("Changes", f"weakens {h['service']}: no direct change", kind="finding")

    def history(self, s, hyps, ctx, emit):
        for h in hyps:
            sim = s.call("History", "similar_incidents", {"service": h["service"], "limit": 3}).data["incidents"]
            les = s.call("History", "lessons_for", {"service": h["service"]}).data["lessons"]
            same = [i for i in sim if "same root-cause service" in i["why"]]
            own_lessons = [l for l in les if l["about"] == h["service"]]
            emit("History", f"similar_incidents/lessons_for({h['service']}): {len(same)} past incidents on it, {len(own_lessons)} lessons")
            if same:
                i = same[0]
                text = f"Same pattern as {i['incident_id']} ({i['title']}), fixed by {i['action']} in {i['ttr_min']} min."
                cites = [f"Incident:{i['incident_id']}"] + [f"Lesson:{l['pattern']}" for l in own_lessons[:1]]
                s.add_finding("History", h["id"], text, True, cites, weight=1.0)
                h["precedent"] = dict(incident=i["incident_id"], action=i["action"], ttr=i["ttr_min"], fix=(own_lessons[0]["fix"] if own_lessons else i["resolution"]),
                                      times_seen=(own_lessons[0]["times_seen"] if own_lessons else len(same)))
                emit("History", f"supports {h['service']}: {i['incident_id']}", kind="finding")

    def people(self, s, hyps, ctx, emit):
        h = hyps[0]
        r = s.call("People", "find_experts", {"service": h["service"], "at_time": ctx["now"]})
        ex = r.data["experts"]
        awake = [p for p in ex if p["awake"]]
        pick = (awake or ex)[:2]
        emit("People", f"find_experts({h['service']}): {len(ex)} people, {len(awake)} awake now")
        if pick:
            text = "Page " + " and ".join(f"{p['name']} ({'; '.join(p['roles'])}; local {p['local_time']}, {'awake' if p['awake'] else 'asleep'})" for p in pick) + f"; channel {r.data['owner_channel']}."
            s.add_finding("People", h["id"], text, True, [f"Person:{p['handle']}" for p in pick] + [f"Team:{r.data['owner_team']}"], weight=0.5)
            h["people"] = dict(pick=[dict(name=p["name"], handle=p["handle"], awake=p["awake"], roles=p["roles"], local_time=p["local_time"]) for p in pick], channel=r.data["owner_channel"])
            emit("People", f"{', '.join(p['name'] for p in pick)}", kind="finding")

    # ---- Lead decision ---------------------------------------------------------------------------------------
    def decide(self, s, hyps, board, ctx, emit):
        by_id = {b["hypothesis_id"]: b for b in board}
        best, best_pts = None, -1
        for h in hyps:
            fs = by_id[h["id"]]["findings"]
            kinds = {f["kind"] for f in fs if f["effect"] == "supports" and f["weight"] >= 0.5}
            against = [f for f in fs if f["effect"] == "weakens"]
            h["support_kinds"] = sorted(kinds)
            pts = h["structural_score"] + 0.15 * len(kinds) - 0.15 * len(against)
            if pts > best_pts:
                best, best_pts = h, pts
        top = ctx["ranking"]["candidates"][0]
        rank1 = next(c for c in ctx["ranking"]["candidates"] if c["candidate"] == best["service"])
        multi = ctx["ranking"]["likely_multiple_causes"] or ctx["ranking"]["weak_fit"] or len(top["unexplained"]) >= 2
        if multi:
            reasons = [f"No single service explains the storm well: best fit {top['candidate']} scores {top['score']} and leaves {len(top['unexplained'])} alert(s) unexplained ({', '.join(top['unexplained'])}).",
                       "Likely more than one cause, or missing monitoring data."]
            cs = ctx["ranking"].get("cause_set") or []
            if cs:
                reasons.append("The alerts split cleanly into two groups: " + "; ".join(f"{c['candidate']} would explain {len(c['explains'])}" for c in cs)
                               + ". Treat these as leads for two separate causes (the second may sit a layer below the service named).")
            reasons.append("What would settle it: check the unexplained services for their own recent changes and look for a second fault.")
            return dict(root_cause=None, confidence="low", reasons=reasons, cites=[f"Service:{top['candidate']}"], blames_deploy=None, best=None)
        kinds = set(best.get("support_kinds", []))
        reasons = [f"{best['service']} explains {len(rank1['explains'])} of {ctx['n_alerting']} alerts and predicts {len(rank1['predicts'])} services; {len(rank1['predicted_not_alerting'])} predicted are not alerting."]
        cites = [f"Service:{best['service']}"]
        if "temporal" in kinds and best.get("deploy"):           # a model may support "temporal" via a dependency's change; only a direct deploy is blamed
            c = best["deploy"]
            reasons.append(f"{c['kind']} deploy {c['deploy_id']} to it shipped {c['minutes_before']} min before the first alert.")
            cites.append(f"Deploy:{c['deploy_id']}")
        if "historical" in kinds and best.get("precedent"):
            p = best["precedent"]
            reasons.append(f"Same pattern as {p['incident']}, fixed by {p['action']} in {p['ttr']} min.")
            cites.append(f"Incident:{p['incident']}")
        if rank1["score"] >= STRONG_FIT and "temporal" in kinds and len(kinds) >= 2:
            conf = "high"
        elif rank1["score"] >= ABSTAIN_BELOW and len(kinds) >= 1:
            conf = "medium"
        else:
            conf = "low"
        return dict(root_cause=best["service"], confidence=conf, reasons=reasons, cites=cites,
                    blames_deploy=best["deploy"]["deploy_id"] if "temporal" in kinds and best.get("deploy") else None, best=best)


def _first_alert_ts(graph, alerting, now):
    r = graph.query("UNWIND $a AS n MATCH (x:Alert)-[:ON]->(:Service {name:n}) WHERE x.ts <= $now RETURN min(x.ts)", {"a": alerting, "now": now}).result_set
    return r[0][0] if r and r[0][0] else now


def run_investigation(graph, alerting, now=None, emit=None, policy=None, model="rules"):
    """Run a full investigation. `emit(event_dict)` receives live progress events (used for SSE)."""
    t0 = time.time()
    now = int(now if now is not None else time.time())
    policy = policy or RulePolicy()
    events = []

    def push(agent, text, kind="step", **extra):
        e = dict(type=kind, agent=agent, text=text, t=round(time.time() - t0, 2), **extra)
        events.append(e)
        if emit:
            emit(e)

    alerting = sorted(set(alerting))
    s = start_investigation(graph, alerting, model=getattr(policy, "name", model), now=now)
    ctx = dict(alerting=alerting, n_alerting=len(alerting), now=now, first_alert_ts=_first_alert_ts(graph, alerting, now))
    s.listener = lambda agent, tool, params, cites: push(agent, tool, kind="read", tool=tool,
                                                         services=[c.split(":", 1)[1] for c in cites if c.startswith("Service:")][:40])
    push("Lead", f"{len(alerting)} services alerting: {', '.join(alerting)}", kind="start", investigation=s.inv_id)

    rr = s.call("Lead", "rank_root_causes", {"alerting": alerting})
    ctx["ranking"] = rr.data
    cands = rr.data["candidates"][:TOP_K]
    hyp_ids = s.create_hypotheses(cands)
    hyps = [dict(id=hid, service=c["candidate"], rank=c["rank"], structural_score=c["score"], coverage=c["coverage"], precision=c["precision"],
                 summary=c["summary"]) for hid, c in zip(hyp_ids, cands)]
    push("Lead", "Top hypotheses: " + "; ".join(f"{h['service']} ({h['structural_score']})" for h in hyps), kind="hypotheses", hypotheses=[
        dict(id=h["id"], service=h["service"], score=h["structural_score"], coverage=h["coverage"], precision=h["precision"], summary=h["summary"]) for h in hyps])

    jobs = [("Impact", policy.impact), ("Changes", policy.changes), ("History", policy.history), ("People", policy.people)]
    shared = {h["id"]: h for h in hyps}      # specialists annotate their own keys on each hypothesis

    def run(job):
        agent, fn = job
        fn(s, hyps, ctx, lambda a, t, kind="step", **x: push(a, t, kind, **x))

    with ThreadPoolExecutor(max_workers=4) as ex:
        for f in [ex.submit(run, j) for j in jobs]:
            f.result()

    board = s.read_board()
    push("Lead", "Read the board from the graph: " + "; ".join(f"{b['service']}: {len(b['findings'])} findings" for b in board))
    d = policy.decide(s, hyps, board, ctx, lambda a, t, kind="step", **x: push(a, t, kind, **x))

    return conclude(graph, s, d, hyps, board, ctx, alerting, push, t0)


def conclude(graph, s, d, hyps, board, ctx, alerting, push, t0):
    """Everything after the Lead has decided: simulate the fix, record the decision, draft the message. Shared with ripple."""
    actions, verification = [], None
    if d["root_cause"]:
        best = d["best"]
        dep = best.get("deploy")
        precedent = best.get("precedent")
        kind = dep["kind"] if dep else None
        action = (precedent or {}).get("action") or ("rollback" if kind in (None, "config", "code") else "restart")
        if action == "rollback" and not dep:
            action = "restart"
        args = dict(action=action, service=d["root_cause"], current_alerting=alerting)
        if action == "rollback":
            args["deploy_id"] = dep["deploy_id"]
        v = s.call("Lead", "verify_mitigation", args)
        verification = v.data
        push("Lead", v.data["summary"], kind="verify", verification=v.data)
        cites = d["cites"] + [c for c in v.cites if c.startswith("Service:") and c in s.seen["Lead"]]
        s.propose_action("Lead", action, d["root_cause"], args.get("deploy_id"),
                         f"{action} on {d['root_cause']}" + (f" (deploy {args['deploy_id']})" if args.get("deploy_id") else "") + f"; simulation: {v.data['summary']}", d["cites"])
        actions = s.proposed
    rec = s.record_decision(d["root_cause"], d["confidence"], d["reasons"], d["cites"], blames_deploy=d["blames_deploy"])
    push("Lead", f"Decision: {rec['root_cause']} ({rec['confidence']} confidence). " + " ".join(rec["reasons"]), kind="decision", decision=rec)

    best = d.get("best") or {}
    message = draft_message(rec, best, actions, ctx)
    graph.query("MATCH (:Investigation {id:$i})-[:CONCLUDED]->(d:Decision) SET d.message = $m", {"i": s.inv_id, "m": message})
    graph.query("MATCH (i:Investigation {id:$i}) SET i.duration_ms = $ms", {"i": s.inv_id, "ms": int((time.time() - t0) * 1000)})
    result = dict(investigation=s.inv_id, root_cause=rec["root_cause"], confidence=rec["confidence"], reasons=rec["reasons"],
                  claims=s.verification(), hypotheses=hyps, board=board, actions=actions, verification=verification,
                  impact=best.get("impact"), people=best.get("people"), precedent=best.get("precedent"), message=message,
                  duration_s=round(time.time() - t0, 2), alerting=alerting, blames_deploy=d["blames_deploy"])
    push("Lead", f"Done in {result['duration_s']} s. Claims verified: {result['claims']['verified']}/{result['claims']['verified'] + result['claims']['rejected']}", kind="done", result=result)
    return result


def draft_message(rec, best, actions, ctx):
    if rec["root_cause"] == "undetermined":
        return (f"[INCIDENT] {ctx['n_alerting']} services alerting. Root cause UNDETERMINED (low confidence): likely more than one cause or missing data. "
                + " ".join(rec["reasons"]))
    lines = [f"[INCIDENT] {ctx['n_alerting']} services alerting. Likely root cause: {rec['root_cause']} ({rec['confidence']} confidence).", *rec["reasons"]]
    imp = best.get("impact")
    if imp:
        lines.append(f"Impact: features {', '.join(imp['features'])}; {imp['customers']} customers; ARR at risk {imp['arr']:,}.")
    if actions:
        a = actions[0]
        lines.append(f"Proposed action: {a['action']} on {a['service']}" + (f" (deploy {a['deploy_id']})" if a.get("deploy_id") else "") + " - needs human approval.")
    pp = best.get("people")
    if pp:
        lines.append("Page: " + ", ".join(f"{p['name']} ({'awake' if p['awake'] else 'asleep'})" for p in pp["pick"]) + f" in {pp['channel']}.")
    return "\n".join(lines)
