"""Memory write-back: resolving an investigation stores an Incident + Resolution and updates a Lesson.

Human-only (the UI's "Mark resolved" button). Disabled during benchmarks so the docs-only baseline is compared fairly.
"""
import time

from backend.tools.base import rows


def record_resolution(graph, inv_id, action, summary, ttr_min, now=None, responders=()):
    now = int(now if now is not None else time.time())
    d = rows(graph, """MATCH (:Investigation {id:$i})-[:CONCLUDED]->(d:Decision) RETURN d.root_cause""", {"i": inv_id})
    if not d:
        raise ValueError(f"{inv_id} has no decision yet")
    root = d[0][0]
    if root == "undetermined":
        raise ValueError("cannot record a resolution for an undetermined decision")
    blamed = rows(graph, """MATCH (:Investigation {id:$i})-[:CONCLUDED]->(:Decision)-[:BLAMES]->(x:Deploy) RETURN x.id, x.kind""", {"i": inv_id})
    kind = blamed[0][1] if blamed else "unknown"
    n = rows(graph, "MATCH (i:Incident) RETURN count(i)")[0][0]
    inc_id = f"INC-{101 + n}"
    first = rows(graph, "MATCH (:Investigation {id:$i})-[:TRIGGERED_BY]->(a:Alert) RETURN min(a.ts)", {"i": inv_id})[0][0] or now
    graph.query("""MATCH (i:Investigation {id:$i}), (s:Service {name:$root})
                   CREATE (n:Incident {id:$id, title:$title, summary:$summ, severity:'sev2', started_at:$start, resolved_at:$now}),
                          (i)-[:BECAME]->(n),
                          (n)-[:RESOLVED_BY]->(:Resolution {summary:$res, action:$action, ttr_min:$ttr}),
                          (n)-[:AFFECTED]->(s)""",
                dict(i=inv_id, root=root, id=inc_id, title=f"{root} degraded after {kind} change",
                     summ=f"{kind} change to {root}. {summary}", start=first, now=now, res=summary, action=action, ttr=float(ttr_min)))
    graph.query("""MATCH (:Investigation {id:$i})-[:CONCLUDED]->(:Decision)-[:BLAMES]->(x:Deploy), (n:Incident {id:$id})
                   CREATE (n)-[:CAUSED_BY]->(x)""", {"i": inv_id, "id": inc_id})
    graph.query("""UNWIND $hs AS h MATCH (n:Incident {id:$id}), (p:Person {handle:h}) CREATE (p)-[:RESPONDED_TO]->(n)""",
                {"hs": list(responders), "id": inc_id})
    pattern = f"{root}: {kind} change fixed by {action}"
    ex = rows(graph, "MATCH (l:Lesson {pattern:$p}) RETURN l.times_seen, l.avg_ttr_min", {"p": pattern})
    if ex:
        seen, avg = ex[0]
        graph.query("MATCH (l:Lesson {pattern:$p}) SET l.times_seen = $n, l.last_seen = $now, l.avg_ttr_min = $avg",
                    {"p": pattern, "n": seen + 1, "now": now, "avg": round((avg * seen + float(ttr_min)) / (seen + 1), 1)})
    else:
        graph.query("""MATCH (s:Service {name:$root}), (n:Incident {id:$id})
                       CREATE (l:Lesson {pattern:$p, fix:$fix, times_seen:1, last_seen:$now, avg_ttr_min:$ttr}),
                              (l)-[:ABOUT]->(s), (l)-[:LEARNED_FROM]->(n)""",
                    dict(root=root, id=inc_id, p=pattern, fix=summary, now=now, ttr=float(ttr_min)))
    graph.query("MATCH (i:Investigation {id:$i}) SET i.status = 'resolved'", {"i": inv_id})
    return dict(incident_id=inc_id, lesson=pattern)
