"""Read tools: every one is parameterized Cypher (values are never pasted into query text)."""
import re
import time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from backend.tools.base import ToolResult, cite, require_services, rows


def _receipt(tool, **params):
    return {"tool": tool, "params": params}


def dependencies(graph, service, kind=None, max_hops=6) -> ToolResult:
    """What `service` relies on (transitively), with hop counts."""
    require_services(graph, [service])
    max_hops = max(1, min(int(max_hops), 6))
    if kind in ("sync", "async"):
        q = f"""MATCH p=(s:Service {{name:$service}})-[:DEPENDS_ON*1..{max_hops} {{kind:$kind}}]->(d:Service)
                RETURN d.name, d.layer, d.monitored, min(length(p)) ORDER BY min(length(p)), d.name"""
    else:
        q = f"""MATCH p=(s:Service {{name:$service}})-[:DEPENDS_ON*1..{max_hops}]->(d:Service)
                RETURN d.name, d.layer, d.monitored, min(length(p)) ORDER BY min(length(p)), d.name"""
    res = rows(graph, q, {"service": service, "kind": kind})
    deps = [dict(service=n, layer=l, monitored=m, hops=h) for n, l, m, h in res]
    direct = rows(graph, "MATCH (s:Service {name:$service})-[r:DEPENDS_ON]->(d:Service) RETURN d.name, r.kind ORDER BY d.name", {"service": service})
    data = dict(service=service, direct=[dict(service=n, kind=k) for n, k in direct], all=deps)
    return ToolResult(data, [cite("Service", service)] + [cite("Service", d["service"]) for d in deps],
                      _receipt("dependencies", service=service, kind=kind, max_hops=max_hops))


def blast_radius(graph, service) -> ToolResult:
    """Failing now (sync dependents) vs at risk soon (async dependents), plus features, customers and ARR."""
    require_services(graph, [service])
    failing = {n: h for n, h in rows(graph, """
        MATCH p=(u:Service)-[:DEPENDS_ON*1..6 {kind:'sync'}]->(s:Service {name:$service})
        RETURN u.name, min(length(p))""", {"service": service})}
    names = [service] + sorted(failing)
    at_risk = sorted({r[0] for r in rows(graph, """
        MATCH (a:Service)-[:DEPENDS_ON {kind:'async'}]->(b:Service) WHERE b.name IN $names
        RETURN DISTINCT a.name""", {"names": names})} - set(names))
    feats = sorted(r[0] for r in rows(graph, """
        MATCH (f:Feature)-[:USES]->(x:Service) WHERE x.name IN $names RETURN DISTINCT f.name""", {"names": names}))
    custs = rows(graph, """
        MATCH (c:Customer)-[:USES]->(f:Feature) WHERE f.name IN $feats
        RETURN DISTINCT c.name, c.plan, c.arr ORDER BY c.arr DESC, c.name""", {"feats": feats})
    customers = [dict(name=n, plan=p, arr=a) for n, p, a in custs]
    data = dict(
        service=service,
        failing_now=[dict(service=n, hops=failing[n]) for n in sorted(failing, key=lambda x: (failing[x], x))],
        at_risk_async=at_risk, features=feats, customers=customers,
        customers_by_plan={p: sum(1 for c in customers if c["plan"] == p) for p in ("enterprise", "pro", "free")},
        arr_at_risk=sum(c["arr"] for c in customers))     # summed once per distinct customer, in Python
    cites = [cite("Service", n) for n in names + at_risk] + [cite("Feature", f) for f in feats] + [cite("Customer", c["name"]) for c in customers]
    return ToolResult(data, cites, _receipt("blast_radius", service=service))


def recent_changes(graph, services, until_ts, window_minutes=120, hops=2) -> ToolResult:
    """Deploys to `services` and to what they sync-depend on (up to `hops`), in the window before `until_ts`."""
    services = sorted(set(services))
    require_services(graph, services)
    hops = max(0, min(int(hops), 4))
    since = int(until_ts) - int(window_minutes) * 60
    res = rows(graph, f"""
        UNWIND $services AS n
        MATCH p=(s:Service {{name:n}})-[:DEPENDS_ON*0..{hops} {{kind:'sync'}}]->(t:Service)
        MATCH (d:Deploy)-[:TO]->(t) WHERE d.ts >= $since AND d.ts <= $until
        MATCH (a:Person)-[:SHIPPED]->(d)
        RETURN d.id, d.ts, d.kind, d.summary, t.name, a.handle, collect(DISTINCT n), min(length(p))
        ORDER BY d.ts DESC""", {"services": services, "since": since, "until": int(until_ts)})
    changes = [dict(deploy_id=i, ts=ts, minutes_before=round((until_ts - ts) / 60), kind=k, summary=sm, service=svc,
                    author=au, relevant_to=sorted(rel), hops_from_suspect=h)
               for i, ts, k, sm, svc, au, rel, h in res]
    data = dict(until_ts=int(until_ts), window_minutes=int(window_minutes), changes=changes)
    cites = [cite("Deploy", c["deploy_id"]) for c in changes] + [cite("Service", c["service"]) for c in changes] \
        + [cite("Service", s) for s in services]
    return ToolResult(data, cites, _receipt("recent_changes", services=services, until_ts=int(until_ts),
                                            window_minutes=int(window_minutes), hops=hops))


def change_details(graph, deploy_id) -> ToolResult:
    r = rows(graph, """
        MATCH (d:Deploy {id:$id})-[:TO]->(s:Service), (a:Person)-[:SHIPPED]->(d)
        OPTIONAL MATCH (a)-[:MEMBER_OF]->(t:Team)
        RETURN d.id, d.ts, d.kind, d.summary, d.diff, s.name, a.handle, a.name, t.name""", {"id": deploy_id})
    if not r:
        raise ValueError(f"unknown deploy: {deploy_id}")
    i, ts, kind, summ, diff, svc, handle, pname, team = r[0]
    commits = [dict(sha=sh, message=m) for sh, m in rows(graph, "MATCH (:Deploy {id:$id})-[:INCLUDES]->(c:Commit) RETURN c.sha, c.message ORDER BY c.sha", {"id": deploy_id})]
    data = dict(deploy_id=i, ts=ts, kind=kind, summary=summ, diff=diff, service=svc,
                author=dict(handle=handle, name=pname, team=team), commits=commits)
    cites = [cite("Deploy", i), cite("Service", svc), cite("Person", handle)] + [cite("Commit", c["sha"]) for c in commits]
    return ToolResult(data, cites, _receipt("change_details", deploy_id=deploy_id))


AWAKE_FROM, AWAKE_TO = 8, 22   # local hours when we assume someone can be paged


def find_experts(graph, service, at_time=None) -> ToolResult:
    """Who to page: owning team's on-call, recent change authors, past resolvers; flags who is awake at `at_time`."""
    require_services(graph, [service])
    at_time = int(at_time if at_time is not None else time.time())
    people = {}

    def person(handle, name, tz, team):
        p = people.setdefault(handle, dict(handle=handle, name=name, timezone=tz, team=team, roles=[], score=0))
        return p

    owner = rows(graph, "MATCH (s:Service {name:$s})-[:OWNED_BY]->(t:Team) RETURN t.name, t.channel", {"s": service})[0]
    for h, n, tz, oc in rows(graph, """
            MATCH (s:Service {name:$s})-[:OWNED_BY]->(t:Team)<-[:MEMBER_OF]-(p:Person)
            RETURN p.handle, p.name, p.timezone, p.on_call""", {"s": service}):
        p = person(h, n, tz, owner[0])
        p["roles"].append("owning team")
        p["score"] += 1
        if oc:
            p["roles"].append("on-call")
            p["score"] += 3
    for h, n, tz, team, cnt in rows(graph, """
            MATCH (d:Deploy)-[:TO]->(:Service {name:$s}) WHERE d.ts <= $at
            WITH d ORDER BY d.ts DESC LIMIT 3
            MATCH (p:Person)-[:SHIPPED]->(d) OPTIONAL MATCH (p)-[:MEMBER_OF]->(t:Team)
            RETURN p.handle, p.name, p.timezone, t.name, count(d)""", {"s": service, "at": at_time}):
        p = person(h, n, tz, team)
        p["roles"].append(f"shipped {cnt} of the last 3 deploys to {service}")
        p["score"] += 3
    for h, n, tz, team, cnt in rows(graph, """
            MATCH (p:Person)-[:RESPONDED_TO]->(i:Incident)-[:CAUSED_BY]->(:Deploy)-[:TO]->(:Service {name:$s})
            OPTIONAL MATCH (p)-[:MEMBER_OF]->(t:Team)
            RETURN p.handle, p.name, p.timezone, t.name, count(DISTINCT i)""", {"s": service}):
        p = person(h, n, tz, team)
        p["roles"].append(f"resolved {cnt} past incident{'s' if cnt != 1 else ''} on {service}")
        p["score"] += min(cnt, 3)
    out = []
    for p in people.values():
        local = datetime.fromtimestamp(at_time, tz=timezone.utc).astimezone(ZoneInfo(p["timezone"]))
        p["local_time"] = local.strftime("%H:%M")
        p["awake"] = AWAKE_FROM <= local.hour < AWAKE_TO
        if p["awake"]:
            p["score"] += 2
        p["roles"] = sorted(set(p["roles"]))
        out.append(p)
    out.sort(key=lambda p: (-p["score"], p["handle"]))
    data = dict(service=service, owner_team=owner[0], owner_channel=owner[1], at_time=at_time, experts=out,
                note=f"awake = local time between {AWAKE_FROM:02d}:00 and {AWAKE_TO:02d}:00")
    cites = [cite("Service", service), cite("Team", owner[0])] + [cite("Person", p["handle"]) for p in out]
    return ToolResult(data, cites, _receipt("find_experts", service=service, at_time=at_time))


def _ft_query(text):
    words = [w for w in re.findall(r"[A-Za-z0-9]+", text or "") if len(w) > 2]
    return " ".join(words[:12])


def similar_incidents(graph, service, text=None, limit=5) -> ToolResult:
    """Past incidents rooted in this service (strongest), affecting it, or matching `text` (full-text index)."""
    require_services(graph, [service])
    found = {}

    def add(i, title, summ, root, action, ttr, started, res, why, score):
        e = found.setdefault(i, dict(incident_id=i, title=title, summary=summ, root_cause_service=root, action=action,
                                     ttr_min=ttr, started_at=started, resolution=res, why=[], score=0.0))
        e["why"].append(why)
        e["score"] += score

    base = """MATCH (i:Incident)-[:CAUSED_BY]->(:Deploy)-[:TO]->(root:Service)
              MATCH (i)-[:RESOLVED_BY]->(r:Resolution)
              %s RETURN i.id, i.title, i.summary, root.name, r.action, r.ttr_min, i.started_at, r.summary"""
    for row in rows(graph, base % "WHERE root.name = $s", {"s": service}):
        add(*row, why="same root-cause service", score=3.0)
    for row in rows(graph, base.replace("MATCH (i)-[:RESOLVED_BY]", "MATCH (i)-[:AFFECTED]->(:Service {name:$s}) MATCH (i)-[:RESOLVED_BY]") % "WHERE root.name <> $s", {"s": service}):
        add(*row, why="affected this service", score=1.0)
    q = _ft_query(text)
    if q:
        hits = rows(graph, "CALL db.idx.fulltext.queryNodes('Incident', $q) YIELD node, score RETURN node.id, score", {"q": q})
        for iid, sc in hits:
            for row in rows(graph, base % "WHERE i.id = $id", {"id": iid}):
                add(*row, why="text match", score=min(float(sc), 3.0) / 3.0)
    ranked = sorted(found.values(), key=lambda e: (-e["score"], -e["started_at"], e["incident_id"]))[:int(limit)]
    for e in ranked:
        e["score"] = round(e["score"], 3)
    data = dict(service=service, text=text, incidents=ranked)
    cites = [cite("Service", service)] + [cite("Incident", e["incident_id"]) for e in ranked]
    return ToolResult(data, cites, _receipt("similar_incidents", service=service, text=text, limit=int(limit)))


def lessons_for(graph, service) -> ToolResult:
    """Learned procedures (Lessons) about this service or what it sync-depends on (up to 3 hops)."""
    require_services(graph, [service])
    res = rows(graph, """
        MATCH p=(s:Service {name:$s})-[:DEPENDS_ON*0..3 {kind:'sync'}]->(t:Service)<-[:ABOUT]-(l:Lesson)
        RETURN l.pattern, l.fix, l.times_seen, l.last_seen, l.avg_ttr_min, t.name, min(length(p)) - 1 AS hops
        ORDER BY hops, l.times_seen DESC""", {"s": service})
    lessons = [dict(pattern=pa, fix=fx, times_seen=n, last_seen=ls, avg_ttr_min=ttr, about=svc, hops=h) for pa, fx, n, ls, ttr, svc, h in res]
    cites = [cite("Service", service)] + [cite("Lesson", l["pattern"]) for l in lessons] + [cite("Service", l["about"]) for l in lessons]
    return ToolResult(dict(service=service, lessons=lessons), cites, _receipt("lessons_for", service=service))


def critical_services(graph, limit=5) -> ToolResult:
    """Chokepoints (betweenness) and most depended-on services (PageRank)."""
    bt = {n: s for n, s in rows(graph, """CALL algo.betweenness({nodeLabels:['Service'], relationshipTypes:['DEPENDS_ON']})
                                          YIELD node, score RETURN node.name, score""")}
    pr = {n: s for n, s in rows(graph, """CALL algo.pageRank('Service','DEPENDS_ON') YIELD node, score RETURN node.name, score""")}
    ranked = sorted(bt, key=lambda n: (-bt[n], -pr.get(n, 0), n))[:int(limit)]
    items = [dict(service=n, betweenness=round(bt[n], 4), pagerank=round(pr.get(n, 0.0), 4)) for n in ranked]
    return ToolResult(dict(critical=items), [cite("Service", i["service"]) for i in items], _receipt("critical_services", limit=int(limit)))


def path_between(graph, a, b, max_hops=8) -> ToolResult:
    """Shortest DEPENDS_ON path between two services (tries a->b, then b->a)."""
    require_services(graph, [a, b])
    max_hops = max(1, min(int(max_hops), 8))
    best = None
    for src, dst in ((a, b), (b, a)):
        r = rows(graph, f"""MATCH (x:Service {{name:$x}}), (y:Service {{name:$y}})
                           WITH shortestPath((x)-[:DEPENDS_ON*..{max_hops}]->(y)) AS p
                           RETURN [n IN nodes(p) | n.name], length(p)""", {"x": src, "y": dst})
        if r and r[0][0]:
            best = dict(direction=f"{src} depends on {dst}", path=r[0][0], hops=r[0][1])
            break
    data = dict(a=a, b=b, connected=best is not None, **(best or {}))
    cites = [cite("Service", n) for n in (best["path"] if best else [a, b])]
    return ToolResult(data, cites, _receipt("path_between", a=a, b=b, max_hops=max_hops))


def explore_graph(graph, cypher, limit=100, timeout_ms=2000) -> ToolResult:
    """Escape hatch. Runs through GRAPH.RO_QUERY, so the database itself rejects any write."""
    res = graph.ro_query(cypher, timeout=int(timeout_ms))
    out = [list(map(_plain, r)) for r in res.result_set[: int(limit)]]
    return ToolResult(dict(columns=[h[1] if isinstance(h, (list, tuple)) else h for h in res.header], rows=out,
                           truncated=len(res.result_set) > int(limit)), [],
                      _receipt("explore_graph", cypher=cypher, limit=int(limit)))


def _plain(v):
    if hasattr(v, "properties"):
        return dict(v.properties)
    return v
