"""Write a world dict into a FalkorDB graph. Everything is a parameterized UNWIND (no string-built Cypher values)."""
import time

from backend.graph.schema import ensure_schema


def _run(g, q, rows):
    if rows:
        g.query(q, {"rows": rows})


def load_world(graph, world, now=None):
    """Load `world` into `graph`, turning every age_s into a real timestamp relative to `now` (epoch seconds)."""
    now = int(now if now is not None else time.time())
    ensure_schema(graph)
    ts = lambda age: now - int(age)
    graph.query("CREATE (:Meta {loaded_at: $now, world: $world})", {"now": now, "world": world["name"]})

    _run(graph, "UNWIND $rows AS r CREATE (:Team {name:r.name, channel:r.channel})", world["teams"])
    _run(graph, "UNWIND $rows AS r CREATE (:Service {name:r.name, layer:r.layer, tier:r.tier, language:r.language, monitored:r.monitored})", world["services"])
    _run(graph, "UNWIND $rows AS r MATCH (s:Service {name:r.name}),(t:Team {name:r.team}) CREATE (s)-[:OWNED_BY]->(t)", world["services"])
    _run(graph, "UNWIND $rows AS r MATCH (a:Service {name:r.src}),(b:Service {name:r.dst}) CREATE (a)-[:DEPENDS_ON {kind:r.kind}]->(b)", world["deps"])
    _run(graph, "UNWIND $rows AS r CREATE (:Person {name:r.name, handle:r.handle, timezone:r.timezone, on_call:r.on_call})", world["people"])
    _run(graph, "UNWIND $rows AS r MATCH (p:Person {handle:r.handle}),(t:Team {name:r.team}) CREATE (p)-[:MEMBER_OF]->(t)", world["people"])

    _run(graph, "UNWIND $rows AS r CREATE (:Feature {name:r.name})", world["features"])
    _run(graph, "UNWIND $rows AS r UNWIND r.services AS s MATCH (f:Feature {name:r.name}),(x:Service {name:s}) CREATE (f)-[:USES]->(x)", world["features"])
    _run(graph, "UNWIND $rows AS r CREATE (:Customer {name:r.name, plan:r.plan, arr:r.arr})", world["customers"])
    _run(graph, "UNWIND $rows AS r UNWIND r.features AS f MATCH (c:Customer {name:r.name}),(x:Feature {name:f}) CREATE (c)-[:USES]->(x)", world["customers"])
    _run(graph, "UNWIND $rows AS r MATCH (s:Service {name:r.service}) CREATE (:Runbook {title:r.title, steps:r.steps})-[:FOR]->(s)", world["runbooks"])

    load_deploys(graph, world["deploys"], now)

    incs = [dict(i, started_at=ts(i["age_s"]), resolved_at=ts(i["age_s"]) + i["ttr_min"] * 60) for i in world["incidents"]]
    _run(graph, """UNWIND $rows AS r CREATE (i:Incident {id:r.id, title:r.title, summary:r.summary, severity:r.severity,
                   started_at:r.started_at, resolved_at:r.resolved_at})""", incs)
    _run(graph, "UNWIND $rows AS r UNWIND r.affected AS s MATCH (i:Incident {id:r.id}),(x:Service {name:s}) CREATE (i)-[:AFFECTED]->(x)", incs)
    _run(graph, "UNWIND $rows AS r MATCH (i:Incident {id:r.id}),(d:Deploy {id:r.deploy_id}) CREATE (i)-[:CAUSED_BY]->(d)", incs)
    _run(graph, """UNWIND $rows AS r MATCH (i:Incident {id:r.id})
                   CREATE (i)-[:RESOLVED_BY]->(:Resolution {summary:r.resolution, action:r.action, ttr_min:r.ttr_min})""", incs)
    _run(graph, "UNWIND $rows AS r UNWIND r.responders AS h MATCH (i:Incident {id:r.id}),(p:Person {handle:h}) CREATE (p)-[:RESPONDED_TO]->(i)", incs)

    lessons = [dict(l, last_seen=ts(l["last_seen_age_s"])) for l in world["lessons"]]
    _run(graph, """UNWIND $rows AS r MATCH (s:Service {name:r.service}),(i:Incident {id:r.learned_from})
                   CREATE (l:Lesson {pattern:r.pattern, fix:r.fix, times_seen:r.times_seen, last_seen:r.last_seen, avg_ttr_min:r.avg_ttr_min}),
                          (l)-[:ABOUT]->(s), (l)-[:LEARNED_FROM]->(i)""", lessons)
    return now


def load_deploys(graph, deploys, now):
    rows = [dict(d, ts=now - int(d["age_s"])) for d in deploys]
    _run(graph, "UNWIND $rows AS r CREATE (:Deploy {id:r.id, ts:r.ts, kind:r.kind, summary:r.summary, diff:r.diff})", rows)
    _run(graph, "UNWIND $rows AS r MATCH (d:Deploy {id:r.id}),(s:Service {name:r.service}) CREATE (d)-[:TO]->(s)", rows)
    _run(graph, "UNWIND $rows AS r MATCH (d:Deploy {id:r.id}),(p:Person {handle:r.author}) CREATE (p)-[:SHIPPED]->(d)", rows)
    _run(graph, """UNWIND $rows AS r UNWIND r.commits AS c
                   MATCH (d:Deploy {id:r.id}),(p:Person {handle:r.author}),(s:Service {name:r.service})
                   CREATE (d)-[:INCLUDES]->(cm:Commit {sha:c.sha, message:c.message, ts:r.ts - 600}),
                          (p)-[:AUTHORED]->(cm), (cm)-[:TOUCHES]->(s)""", rows)


def load_alerts(graph, alerts, now):
    rows = [dict(a, ts=now - int(a["age_s"])) for a in alerts]
    _run(graph, "UNWIND $rows AS r MATCH (s:Service {name:r.service}) CREATE (:Alert {id:r.id, ts:r.ts, signal:r.signal, severity:r.severity})-[:ON]->(s)", rows)
