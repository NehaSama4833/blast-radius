"""Differential test of FalkorDB's graph algorithms and path queries against independent reference implementations.

Blast Radius trusts FalkorDB for every answer it gives (variable-length paths for the blast radius, shortestPath for
explanations, algo.betweenness and algo.pageRank for "what is critical"). This script checks those operations, and the
other built-in algorithms, on thousands of small random graphs, against NetworkX or a brute-force Python reference.

    python -m bench.fuzz_falkordb --graphs 300 --seed 7 --out bench/results/fuzz_falkordb.json

Every mismatch is saved with the exact graph (edge list), the query and both answers, so it can be replayed.
A mismatch is a *difference*, not automatically a bug: some differences are documented semantics. docs/FALKORDB_FUZZ.md
classifies each one after checking it by hand.
"""
import argparse
import json
import math
import random
import time
from collections import defaultdict

import networkx as nx

from backend.graph.db import get_db, get_graph

G = "fuzz_tmp"


# ---------- random graphs ----------
def random_graph(rng):
    n = rng.randint(2, 12)
    p = rng.choice([0.1, 0.2, 0.3, 0.5])
    edges = []
    for a in range(n):
        for b in range(n):
            if a != b and rng.random() < p:
                edges.append((a, b, rng.choice([1, 2, 3, 5, 8]) if rng.random() < 0.9 else round(rng.uniform(0.5, 9.5), 2)))
    if rng.random() < 0.15 and edges:                      # parallel edges
        a, b, _ = rng.choice(edges)
        edges.append((a, b, rng.choice([1, 4, 7])))
    if rng.random() < 0.10:                                # self loop
        v = rng.randrange(n)
        edges.append((v, v, 2))
    return n, edges


def load(g, n, edges):
    try:
        g.delete()
    except Exception:
        pass
    g.query("UNWIND range(0, $n - 1) AS i CREATE (:N {id: i})", {"n": n})
    if edges:
        g.query("UNWIND $es AS e MATCH (a:N {id: e[0]}), (b:N {id: e[1]}) CREATE (a)-[:E {w: e[2]}]->(b)",
                {"es": [list(e) for e in edges]})


def digraph(n, edges, multi=False):
    D = nx.MultiDiGraph() if multi else nx.DiGraph()
    D.add_nodes_from(range(n))
    for a, b, w in edges:
        if not multi and D.has_edge(a, b):
            D[a][b]["w"] = min(D[a][b]["w"], w)
        else:
            D.add_edge(a, b, w=w)
    return D


# ---------- brute-force references ----------
def trails(n, edges, s, lo, hi):
    """Count paths s -[*lo..hi]-> t with no repeated relationship (Cypher's uniqueness rule), grouped by t."""
    out = defaultdict(int)
    adj = defaultdict(list)
    for i, (a, b, _) in enumerate(edges):
        adj[a].append((i, b))

    def dfs(v, used, depth):
        if lo <= depth <= hi:
            out[v] += 1
        if depth == hi:
            return
        for i, b in adj[v]:
            if i not in used:
                used.add(i)
                dfs(b, used, depth + 1)
                used.remove(i)
    dfs(s, set(), 0)
    return dict(out)


def close(a, b, tol=1e-4):
    return abs(a - b) <= tol * max(1.0, abs(a), abs(b))


# ---------- checks: each returns None (agree) or a dict describing the difference ----------
def _varlen(g, n, edges, rng, named):
    s = rng.randrange(n)
    lo, hi = rng.choice([(1, 1), (1, 2), (1, 3), (0, 2), (2, 3), (1, 4)])
    q = f"MATCH {'p=' if named else ''}(s:N {{id: $s}})-[:E*{lo}..{hi}]->(t:N) RETURN t.id, count(*)"
    got = {r[0]: r[1] for r in g.query(q, {"s": s}).result_set}
    want = trails(n, edges, s, lo, hi)
    if got != want:
        return dict(query=q, params={"s": s}, falkordb=got, reference=want,
                    reach_differs=set(got) != set(want))


def check_varlen_unnamed(g, n, edges, rng):
    return _varlen(g, n, edges, rng, named=False)


def check_varlen_named(g, n, edges, rng):
    return _varlen(g, n, edges, rng, named=True)


def check_reach(g, n, edges, rng):
    s = rng.randrange(n)
    q = "MATCH (s:N {id: $s})-[:E*1..]->(t:N) RETURN DISTINCT t.id"
    got = sorted(r[0] for r in g.query(q, {"s": s}).result_set)
    D = digraph(n, edges)
    want = sorted(nx.descendants(D, s) | ({s} if _on_cycle(D, s) else set()))
    if got != want:
        return dict(query=q, params={"s": s}, falkordb=got, reference=want)


def _on_cycle(D, s):
    return any(nx.has_path(D, x, s) for x in D.successors(s))


def check_shortest(g, n, edges, rng):
    s, t = rng.randrange(n), rng.randrange(n)
    if s == t:
        return None
    q = "MATCH (s:N {id: $s}), (t:N {id: $t}) WITH shortestPath((s)-[:E*]->(t)) AS p RETURN CASE WHEN p IS NULL THEN -1 ELSE length(p) END"
    got = g.query(q, {"s": s, "t": t}).result_set[0][0]
    D = digraph(n, edges)
    want = nx.shortest_path_length(D, s, t) if nx.has_path(D, s, t) else -1
    if got != want:
        return dict(query=q, params={"s": s, "t": t}, falkordb=got, reference=want)


def check_bfs(g, n, edges, rng):
    s = rng.randrange(n)
    depth = rng.choice([1, 2, 3])
    q = "MATCH (s:N {id: $s}) CALL algo.BFS(s, $d, 'E') YIELD nodes RETURN [x IN nodes | x.id]"
    rs = g.query(q, {"s": s, "d": depth}).result_set
    got = sorted(rs[0][0]) if rs else []                  # no row (not an empty list) when nothing is reachable
    D = digraph(n, edges)
    lengths = nx.single_source_shortest_path_length(D, s, cutoff=depth)
    want = sorted(v for v, d in lengths.items() if v != s)
    if got != want:
        return dict(query=q, params={"s": s, "d": depth}, falkordb=got, reference=want)


def check_wcc(g, n, edges, rng):
    q = "CALL algo.WCC({nodeLabels: ['N'], relationshipTypes: ['E']}) YIELD node, componentId RETURN node.id, componentId"
    comp = defaultdict(set)
    for v, c in g.query(q).result_set:
        comp[c].add(v)
    got = sorted(sorted(c) for c in comp.values())
    want = sorted(sorted(c) for c in nx.weakly_connected_components(digraph(n, edges)))
    if got != want:
        return dict(query=q, falkordb=got, reference=want)


def check_pagerank(g, n, edges, rng):
    if len({(a, b) for a, b, _ in edges}) != len(edges) or any(a == b for a, b, _ in edges):
        return None          # parallel edges / self loops: FalkorDB counts a parallel edge once (a choice, not a bug)
    q = "CALL algo.pageRank('N', 'E') YIELD node, score RETURN node.id, score"
    got = {r[0]: r[1] for r in g.query(q).result_set}
    want = nx.pagerank(digraph(n, edges, multi=True), alpha=0.85, tol=1e-10, max_iter=1000)
    if any(not close(got[k], want[k], 2e-3) for k in got):   # isolated nodes may be left out of the result
        return dict(query=q, falkordb=got, reference={k: round(v, 6) for k, v in want.items()})


def check_betweenness(g, n, edges, rng):
    if not edges:
        return None                                       # the relationship type does not exist yet: FalkorDB errors
    q = "CALL algo.betweenness({nodeLabels: ['N'], relationshipTypes: ['E']}) YIELD node, score RETURN node.id, score"
    got = {r[0]: r[1] for r in g.query(q).result_set}
    want = nx.betweenness_centrality(digraph(n, edges), normalized=False)
    if set(got) != set(want) or any(not close(got[k], want[k]) for k in want):
        return dict(query=q, falkordb=got, reference={k: round(v, 6) for k, v in want.items()})


def check_sppaths(g, n, edges, rng):
    s, t = rng.randrange(n), rng.randrange(n)
    if s == t:
        return None
    q = ("MATCH (s:N {id: $s}), (t:N {id: $t}) CALL algo.SPpaths({sourceNode: s, targetNode: t, relTypes: ['E'], "
         "weightProp: 'w', pathCount: 1}) YIELD pathWeight RETURN pathWeight")
    rs = g.query(q, {"s": s, "t": t}).result_set
    got = rs[0][0] if rs else None
    D = digraph(n, edges)
    want = nx.dijkstra_path_length(D, s, t, weight="w") if nx.has_path(D, s, t) else None
    if (got is None) != (want is None) or (got is not None and not close(got, want)):
        return dict(query=q, params={"s": s, "t": t}, falkordb=got, reference=want)


def check_msf(g, n, edges, rng):
    if not edges:
        return None                                       # the relationship type does not exist yet: FalkorDB errors
    q = "CALL algo.MSF({nodeLabels: ['N'], relationshipTypes: ['E'], weightAttribute: 'w'}) YIELD edges RETURN [e IN edges | e.w]"
    got = round(sum(sum(r[0]) for r in g.query(q).result_set), 6)
    U = nx.Graph()
    U.add_nodes_from(range(n))
    for a, b, w in edges:
        if a != b and (not U.has_edge(a, b) or U[a][b]["w"] > w):
            U.add_edge(a, b, w=w)
    want = round(sum(d["w"] for _, _, d in nx.minimum_spanning_edges(U, weight="w", data=True)), 6)
    if not close(got, want):
        return dict(query=q, falkordb=got, reference=want)


def check_betweenness_ours(g, n, edges, rng):
    from backend.tools.centrality import betweenness
    got = betweenness(list(range(n)), [(a, b) for a, b, _ in edges])
    want = nx.betweenness_centrality(digraph(n, edges), normalized=False)
    if any(not close(got[k], want[k]) for k in want):
        return dict(falkordb=None, ours=got, reference=want)


CHECKS = dict(varlen_unnamed=check_varlen_unnamed, varlen_named=check_varlen_named, reach=check_reach, shortestPath=check_shortest, bfs=check_bfs, wcc=check_wcc,
              pagerank=check_pagerank, betweenness=check_betweenness, sppaths=check_sppaths, msf=check_msf,
              betweenness_blast_radius=check_betweenness_ours)


def server_version():
    try:
        mods = get_db().connection.execute_command("MODULE", "LIST")
        for m in mods:
            m = m if isinstance(m, dict) else dict(zip(m[::2], m[1::2]))
            if m.get("name") == "graph":
                v = int(m["ver"])
                return f"{v // 10000}.{v // 100 % 100}.{v % 100}"
    except Exception:
        return "unknown"


def run(graphs=300, seed=7, only=None):
    rng = random.Random(seed)
    g = get_graph(G)
    stats = {k: dict(runs=0, diffs=0, errors=0) for k in CHECKS}
    diffs = []
    t0 = time.time()
    for i in range(graphs):
        n, edges = random_graph(rng)
        load(g, n, edges)
        for name, fn in CHECKS.items():
            if only and name not in only:
                continue
            stats[name]["runs"] += 1
            try:
                d = fn(g, n, edges, rng)
            except Exception as e:
                stats[name]["errors"] += 1
                d = dict(error=f"{type(e).__name__}: {e}"[:300])
            if d:
                stats[name]["diffs"] += 1 if "error" not in d else 0
                if d.get("reach_differs"):
                    stats[name]["missing_nodes"] = stats[name].get("missing_nodes", 0) + 1
                if sum(1 for x in diffs if x["check"] == name) < 8:      # keep a few examples of each
                    diffs.append(dict(check=name, graph=i, n=n, edges=edges, **d))
    try:
        g.delete()
    except Exception:
        pass
    return dict(falkordb=server_version(), graphs=graphs, seed=seed, seconds=round(time.time() - t0, 1),
                stats=stats, examples=diffs)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--graphs", type=int, default=300)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--out", default="bench/results/fuzz_falkordb.json")
    a = ap.parse_args()
    res = run(a.graphs, a.seed, a.only)
    with open(a.out, "w") as fh:
        json.dump(res, fh, indent=1, default=str)
    print(f"FalkorDB {res['falkordb']}, {a.graphs} random graphs, {res['seconds']}s")
    for k, s in res["stats"].items():
        extra = f"  (wrong set of reachable nodes: {s['missing_nodes']})" if s.get("missing_nodes") else ""
        print(f"  {k:25s} runs {s['runs']:5d}  differences {s['diffs']:4d}  errors {s['errors']:3d}{extra}")


if __name__ == "__main__":
    main()
