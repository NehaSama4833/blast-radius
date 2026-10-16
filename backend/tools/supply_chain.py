"""Supply-chain triage on the `pypi` world: which recent release explains the packages that just started failing?

One Cypher query does the graph work: from each failing package, walk required dependencies (up to `hops`), keep the
packages that had a release in the time window, and collect which failing packages each release can explain.
Each release gets coverage (share of failures it can explain) and precision (share of the package's dependents that
are failing). Ranking: coverage first, then F1, then the newer release. Unlike the company worlds, a broken library
breaks only *some* of its dependents (many pin versions or avoid the changed API), so precision is a weak signal
here: on the 14 dev incidents F1-first found 25/42 culprits and coverage-first 40/42 (docs/ECOSYSTEMS.md). That run chose
this default; the 7 test incidents were run once afterwards.

Query shape note: the walk has a path variable and a property filter and starts at 0 or 1 hop, a shape checked
against brute force in test_our_query_shapes_are_not_affected_by_f1 (docs/FALKORDB_FINDINGS.md);
bench/pypi_incidents.py also cross-checks every answer with a Python BFS.
"""
from backend.tools.base import ToolResult, cite, rows


def suspect_releases(graph, failing, at_ts, window_h=48, hops=2, top_k=5, scoring="coverage") -> ToolResult:
    failing = sorted(set(failing))
    if not failing:
        raise ValueError("failing must list at least one package")
    t0, t1 = int(at_ts) - int(window_h) * 3600, int(at_ts)
    hops = max(1, min(int(hops), 4))
    found = rows(graph, f"""
        UNWIND $failing AS name
        MATCH p=(a:Service {{name: name}})-[:DEPENDS_ON*0..{hops} {{kind: 'sync'}}]->(c:Service)
        WITH DISTINCT a, c
        MATCH (d:Deploy)-[:TO]->(c) WHERE d.ts >= $t0 AND d.ts <= $t1
        WITH c, a, max(d.ts) AS last, collect(d.version) AS versions
        RETURN c.name, collect(DISTINCT a.name), max(last), head(versions)""", {"failing": failing, "t0": t0, "t1": t1})
    if not found:
        return ToolResult(dict(suspects=[], window=[t0, t1], n_failing=len(failing)), [], dict(tool="suspect_releases"))
    cands = [r[0] for r in found]
    dependents = dict(rows(graph, f"""
        UNWIND $c AS name
        MATCH p=(u:Service)-[:DEPENDS_ON*1..{hops} {{kind: 'sync'}}]->(c:Service {{name: name}})
        RETURN name, count(DISTINCT u)""", {"c": cands}))
    n = len(failing)
    out = []
    for name, explains, last, version in found:
        cov = len(explains) / n
        deps = dependents.get(name, 0) + 1                       # the package itself can fail too
        prec = min(1.0, len(explains) / deps)
        f1 = 2 * cov * prec / (cov + prec) if cov + prec else 0.0
        out.append(dict(package=name, version=version, released_at=last, explains=len(explains),
                        coverage=round(cov, 4), precision=round(prec, 4), dependents=deps - 1, f1=round(f1, 4)))
    if scoring == "f1":
        out.sort(key=lambda x: (-x["f1"], -x["coverage"], -x["released_at"], x["package"]))
    else:
        out.sort(key=lambda x: (-x["coverage"], -x["f1"], -x["released_at"], x["package"]))
    top = out[:top_k]
    cites = [cite("Service", x["package"]) for x in top]
    return ToolResult(dict(suspects=top, window=[t0, t1], n_failing=n, n_candidates=len(out)), cites,
                      dict(tool="suspect_releases", window_h=window_h, hops=hops, scoring=scoring))
