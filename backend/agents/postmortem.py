"""Postmortem written FROM THE GRAPH: every line below is read back from nodes the investigation created
(Alerts, Hypotheses, Findings, Decision, Deploy, Incident, Resolution, Lesson). No model writes this, so it
cannot invent anything; it is the investigation's memory, rendered as Markdown."""
import json
import time

from backend.tools.base import rows


def _t(ts):
    return time.strftime("%H:%M UTC", time.gmtime(int(ts))) if ts else "?"


def postmortem(graph, inv_id):
    inv = rows(graph, "MATCH (i:Investigation {id:$i}) RETURN i.ts, i.status, i.model", {"i": inv_id})
    if not inv:
        raise ValueError("unknown investigation")
    started, status, model = inv[0]
    dec = rows(graph, "MATCH (:Investigation {id:$i})-[:CONCLUDED]->(d:Decision) RETURN d.root_cause, d.confidence, d.reasons", {"i": inv_id})
    if not dec:
        raise ValueError("no decision yet")
    root, conf, reasons = dec[0]
    reasons = json.loads(reasons or "[]")
    alerts = rows(graph, """MATCH (:Investigation {id:$i})-[:TRIGGERED_BY]->(a:Alert)-[:ON]->(s:Service)
                            RETURN s.name, min(a.ts), collect(DISTINCT a.signal) ORDER BY min(a.ts)""", {"i": inv_id})
    dep = rows(graph, """MATCH (:Investigation {id:$i})-[:CONCLUDED]->(:Decision)-[:BLAMES]->(d:Deploy)
                         OPTIONAL MATCH (p:Person)-[:SHIPPED]->(d) RETURN d.id, d.kind, d.summary, d.ts, p.name""", {"i": inv_id})
    inc = rows(graph, """MATCH (:Investigation {id:$i})-[:BECAME]->(n:Incident)-[:RESOLVED_BY]->(r:Resolution)
                         OPTIONAL MATCH (l:Lesson)-[:LEARNED_FROM]->(n) RETURN n.id, n.resolved_at, r.action, r.ttr_min, l.pattern""", {"i": inv_id})
    prev = rows(graph, "MATCH (:Investigation {id:$i})-[:PREVIOUSLY_CONCLUDED]->(d:Decision) RETURN d.root_cause, d.confidence", {"i": inv_id})
    board = rows(graph, """MATCH (:Investigation {id:$i})-[:CONSIDERS]->(h:Hypothesis)-[:ABOUT]->(s:Service)
                           OPTIONAL MATCH (a:Agent)-[:WROTE]->(f:Finding)-[r:SUPPORTS|WEAKENS]->(h)
                           RETURN h.rank, s.name, h.status, a.name, type(r), f.text ORDER BY h.rank, f.id""", {"i": inv_id})
    impact = rows(graph, """MATCH (s:Service {name:$r})<-[:DEPENDS_ON*0..6 {kind:'sync'}]-(x:Service)<-[:USES]-(f:Feature)
                            RETURN collect(DISTINCT f.name)""", {"r": root}) if root != "undetermined" else [[[]]]

    title = f"Postmortem: {root} ({inv_id})" if root != "undetermined" else f"Postmortem: undetermined cause ({inv_id})"
    L = [f"# {title}", "", f"*Generated from the investigation graph (no model wrote this page). Status: {status}. Agents: {model}.*", "",
         "## Summary", ""]
    if root == "undetermined":
        L.append(f"{len(alerts)} services alerted. The agents could not single out one cause ({conf} confidence) and said so.")
    else:
        L.append(f"{len(alerts)} services alerted. Root cause: **{root}** ({conf} confidence)."
                 + (f" Trigger: {dep[0][1]} deploy {dep[0][0]} ('{dep[0][2]}') by {dep[0][4] or 'unknown'}." if dep else ""))
    if impact and impact[0][0]:
        L.append(f"Customer features affected: {', '.join(sorted(impact[0][0]))}.")
    L += ["", "## Timeline (UTC)", ""]
    events = []
    if dep:
        events.append((dep[0][3], f"{dep[0][1]} deploy {dep[0][0]} to {root}"))
    if alerts:
        events.append((alerts[0][1], f"first alert: {alerts[0][0]} ({', '.join(alerts[0][2])})"))
        events.append((alerts[-1][1], f"last alert before the investigation: {alerts[-1][0]}"))
    events.append((started, "investigation opened by the agent team"))
    if inc:
        events.append((inc[0][1], f"resolved by {inc[0][2]} (time to resolve {inc[0][3]:g} min), recorded as {inc[0][0]}"))
    L += [f"- {_t(ts)}: {text}" for ts, text in sorted(events, key=lambda e: e[0] or 0)]
    if prev:
        L += ["", f"Earlier verdict replaced after a late alert: {prev[0][0]} ({prev[0][1]})."]
    L += ["", "## Why the agents concluded this", ""] + [f"- {r}" for r in reasons]
    L += ["", "## Hypotheses considered", ""]
    cur = None
    for rank, svc, st, agent, rel, text in board:
        if (rank, svc) != cur:
            cur = (rank, svc)
            L += ["", f"**#{rank} {svc}** ({st})"]
        if text:
            L.append(f"- {agent} {'supports' if rel == 'SUPPORTS' else 'weakens'}: {text}")
    L += ["", "## Alerting services", "", ", ".join(a[0] for a in alerts) or "none"]
    if inc and inc[0][4]:
        L += ["", "## Lesson saved to memory", "", f"`{inc[0][4]}`. The next investigation that sees this pattern will cite it."]
    L += ["", "## Follow-ups (suggested)", ""]
    L += [f"- Add monitoring to {root}: it failed silently." if root != "undetermined" and not rows(graph, "MATCH (s:Service {name:$r}) RETURN s.monitored", {"r": root})[0][0] else "- Review alert coverage for the services involved."]
    if dep:
        L.append(f"- Add a canary or automatic rollback check for {dep[0][1]} changes to {root}.")
    return "\n".join(L) + "\n"
