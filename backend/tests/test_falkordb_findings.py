"""FalkorDB behaviours found by bench/fuzz_falkordb.py, and proof that Blast Radius does not depend on them.

The three `xfail(strict=True)` tests assert the *correct* answer. They fail today (so they are expected failures);
if a FalkorDB release fixes one, the test passes, strict mode turns that into a failure, and CI tells us to update
docs/FALKORDB_FINDINGS.md. CI runs them against the falkordb/falkordb:latest server as well as the embedded build.
"""
import random
from collections import defaultdict

import networkx as nx
import pytest

from bench import falkordb_repros as R
from backend.graph.db import get_graph
from backend.tools.centrality import betweenness


@pytest.mark.xfail(strict=True, reason="F1: unbound typed variable-length pattern misses a reachable node")
def test_f1_unbound_varlen():
    r = R.f1_unbound_varlen_misses_nodes()
    assert r["got"] == r["expected"]


@pytest.mark.xfail(strict=True, reason="F2: a path is never extended past a repeated node")
def test_f2_expansion_past_start():
    r = R.f2_expansion_stops_at_repeated_node()
    assert r["got"] == r["expected"]


@pytest.mark.xfail(strict=True, reason="F3: algo.betweenness samples even when samplingSize >= nodes")
def test_f3_betweenness_exact():
    r = R.f3_betweenness_sampled_even_when_exact_is_cheap()
    assert r["got"] == r["expected"]


def test_our_brandes_matches_networkx():
    rng = random.Random(1)
    for _ in range(60):
        n = rng.randint(2, 25)
        edges = [(a, b) for a in range(n) for b in range(n) if a != b and rng.random() < 0.15]
        edges += [(0, 0)] if rng.random() < 0.2 else []
        D = nx.DiGraph()
        D.add_nodes_from(range(n))
        D.add_edges_from((a, b) for a, b in edges if a != b)
        want = nx.betweenness_centrality(D, normalized=False)
        got = betweenness(list(range(n)), edges)
        assert all(abs(got[v] - want[v]) < 1e-9 for v in range(n))


def _reach(edges, s, lo, hi, reverse=False):
    adj = defaultdict(set)
    for a, b in edges:
        (adj[b] if reverse else adj[a]).add(a if reverse else b)
    seen, frontier = ({s} if lo == 0 else set()), {s}
    for d in range(1, hi + 1):
        frontier = {w for v in frontier for w in adj[v]}
        if d >= lo:
            seen |= frontier
    return seen


def test_our_query_shapes_are_not_affected_by_f1():
    """The ranking and impact queries use bounded variable-length patterns. They carry a property filter
    ({kind:'sync'}) or a path variable, which the fuzzer found are not affected. Check the exact shapes on random
    DAGs whose depth limit binds, which is where F1 shows up."""
    g = get_graph("shape_guard")
    rng = random.Random(4)
    bad_shape_wrong = 0
    for trial in range(80):
        try:
            g.delete()
        except Exception:
            pass
        n = rng.randint(4, 14)
        edges = [(a, b) for a in range(n) for b in range(a + 1, n) if rng.random() < 0.3]
        g.query("UNWIND range(0, $n - 1) AS i CREATE (:Service {name: toString(i), monitored: true})", {"n": n})
        if edges:
            g.query("UNWIND $e AS e MATCH (a:Service {name: toString(e[0])}), (b:Service {name: toString(e[1])}) "
                    "CREATE (a)-[:DEPENDS_ON {kind: 'sync'}]->(b)", {"e": [list(e) for e in edges]})
        s, hi = rng.randrange(n), rng.choice([1, 2, 3])
        down = {int(x) for x in g.query(f"MATCH (a:Service {{name: $s}})-[:DEPENDS_ON*0..{hi} {{kind: 'sync'}}]->(c:Service) "
                                        "RETURN collect(DISTINCT c.name)", {"s": str(s)}).result_set[0][0]}
        up = {int(x) for x in g.query(f"MATCH (u:Service {{monitored: true}})-[:DEPENDS_ON*1..{hi} {{kind: 'sync'}}]->(c:Service {{name: $s}}) "
                                      "RETURN collect(DISTINCT u.name)", {"s": str(s)}).result_set[0][0]}
        named = {int(x) for x in g.query(f"MATCH p=(a:Service {{name: $s}})-[:DEPENDS_ON*1..{hi}]->(c:Service) "
                                         "RETURN collect(DISTINCT c.name)", {"s": str(s)}).result_set[0][0]}
        assert down == _reach(edges, s, 0, hi)
        assert up == _reach(edges, s, 1, hi, reverse=True)
        assert named == _reach(edges, s, 1, hi)
        bare = {int(x) for x in g.query(f"MATCH (a:Service {{name: $s}})-[:DEPENDS_ON*1..{hi}]->(c:Service) "
                                        "RETURN collect(DISTINCT c.name)", {"s": str(s)}).result_set[0][0]}
        bad_shape_wrong += bare != _reach(edges, s, 1, hi)
    f1 = R.f1_unbound_varlen_misses_nodes()
    if f1["got"] != f1["expected"]:     # while F1 exists, the guard has teeth: the affected shape goes wrong on these graphs
        assert bad_shape_wrong > 0
