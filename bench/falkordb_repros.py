"""Minimal reproductions of the FalkorDB behaviours found by the differential fuzzer (bench/fuzz_falkordb.py).

    python -m bench.falkordb_repros            # embedded falkordblite, or FALKORDB_URL=redis://... for a server

Each case builds a tiny graph (3 to 4 nodes), runs one query and prints what FalkorDB returned next to the answer
openCypher semantics (or the algorithm's definition) gives. Exit code 1 if any finding still reproduces.
Write-up: docs/FALKORDB_FINDINGS.md.
"""
import sys

from backend.graph.db import get_db, get_graph


def fresh(name):
    g = get_graph(name)
    try:
        g.delete()
    except Exception:
        pass
    return get_graph(name)


def f1_unbound_varlen_misses_nodes():
    """A bounded variable-length pattern with a relationship type and no path variable misses a reachable node.

    DAG: a->b, a->c, b->c, c->d.  Within 2 hops of a: b, c (twice: a->c and a->b->c) and d (a->c->d)."""
    g = fresh("repro_f1")
    g.query("CREATE (a:N {name:'a'}), (b:N {name:'b'}), (c:N {name:'c'}), (d:N {name:'d'}) "
            "CREATE (a)-[:E]->(b), (a)-[:E]->(c), (b)-[:E]->(c), (c)-[:E]->(d)")
    q = "MATCH (:N {name:'a'})-[:E*1..2]->(t:N) RETURN t.name ORDER BY t.name"
    got = [r[0] for r in g.query(q).result_set]
    with_path = [r[0] for r in g.query(q.replace("MATCH (", "MATCH p=(", 1)).result_set]
    untyped = [r[0] for r in g.query(q.replace("[:E*1..2]", "[*1..2]")).result_set]
    return dict(query=q, expected=["b", "c", "c", "d"], got=got,
                notes=f"same query with a path variable p=...: {with_path}; without the type [*1..2]: {untyped}")


def f2_expansion_stops_at_repeated_node():
    """A path that repeats a node is returned, but never extended past that node, though no relationship repeats.

    Graph: a->b, b->c, c->b, b->d.  a-[*4]->d exists: a->b->c->b->d uses four different relationships.
    FalkorDB returns a->b->c->b for *3 (so repeating b is allowed) but nothing for *4. Same with a self loop."""
    g = fresh("repro_f2")
    g.query("CREATE (a:N {name:'a'}), (b:N {name:'b'}), (c:N {name:'c'}), (d:N {name:'d'}) "
            "CREATE (a)-[:E]->(b), (b)-[:E]->(c), (c)-[:E]->(b), (b)-[:E]->(d)")
    q = "MATCH p=(:N {name:'a'})-[:E*4]->(t:N) RETURN [x IN nodes(p) | x.name] AS ns"
    got = [r[0] for r in g.query(q).result_set]
    three = [r[0] for r in g.query(q.replace("*4", "*3")).result_set]
    return dict(query=q, expected=[["a", "b", "c", "b", "d"]], got=got,
                notes=f"*3 returns {three}: the repeat is allowed as the last hop. openCypher only forbids reusing a relationship")


def f3_betweenness_sampled_even_when_exact_is_cheap():
    """algo.betweenness on the chain a->b->c: exactly one shortest path (a to c) passes through b, so b scores 1.

    FalkorDB samples source nodes even when samplingSize >= node count, so b scores 0, 1 or 2 depending on the seed,
    and with the default settings 0 or 2 depending on the order the nodes were created in."""
    g = fresh("repro_f3")
    g.query("CREATE (:N {name:'a'})-[:E]->(:N {name:'b'})-[:E]->(:N {name:'c'})")
    q = ("CALL algo.betweenness({nodeLabels:['N'], relationshipTypes:['E'], samplingSize: 300, samplingSeed: $s}) "
         "YIELD node, score WHERE node.name = 'b' RETURN score")
    got = sorted({g.query(q, {"s": s}).result_set[0][0] for s in range(8)})
    return dict(query=q, expected=[1.0], got=got, notes="distinct scores for b over samplingSeed 0..7, samplingSize 300")


FINDINGS = [f1_unbound_varlen_misses_nodes, f2_expansion_stops_at_repeated_node, f3_betweenness_sampled_even_when_exact_is_cheap]


def version():
    try:
        for m in get_db().connection.execute_command("MODULE", "LIST"):
            m = m if isinstance(m, dict) else dict(zip(m[::2], m[1::2]))
            if m.get("name") == "graph":
                v = int(m["ver"])
                return f"{v // 10000}.{v // 100 % 100}.{v % 100}"
    except Exception:
        pass
    return "unknown"


def main():
    print(f"FalkorDB {version()}")
    still = 0
    for f in FINDINGS:
        r = f()
        bad = r["got"] != r["expected"]
        still += bad
        print(f"\n[{'REPRODUCES' if bad else 'fixed'}] {f.__name__}\n  {r['query']}\n  expected {r['expected']}\n  got      {r['got']}\n  {r['notes']}")
    sys.exit(1 if still else 0)


if __name__ == "__main__":
    main()
