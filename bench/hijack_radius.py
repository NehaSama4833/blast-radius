"""Supply-chain blast radius: if one package's next release were malicious, how many packages would pull it in?

For each ecosystem (PyPI, npm), count every package that depends on X through required/runtime dependencies within
3 hops, i.e. would install X's new release on its next fresh install or CI run. The ranking is computed with a
reverse BFS over the snapshot, and the top of the list is re-counted inside FalkorDB with Cypher; the two must match.

    python -m bench.hijack_radius            # writes bench/results/hijack_radius.json

Real incidents are marked, to show where hijacked or sabotaged packages sat on this list.
"""
import json
import time
from collections import defaultdict

from backend.graph.db import get_graph

HOPS = 3
REAL = {"pypi": {"ctx": "hijacked (2022)"},
        "npm": {"ua-parser-js": "hijacked (2021)", "event-stream": "malicious dependency (2018)", "colors": "sabotaged (2022)",
                "node-ipc": "protestware (2022)", "coa": "hijacked (2021)", "rc": "hijacked (2021)", "is-promise": "broken release (2020)"}}


def reverse_reach(edges, hops=HOPS):
    dependents = defaultdict(set)
    for a, b in edges:
        dependents[b].add(a)

    def count(x):
        seen, frontier = {x}, {x}
        for _ in range(hops):
            frontier = {d for f in frontier for d in dependents[f]} - seen
            seen |= frontier
        return len(seen) - 1
    return dependents, count


def cypher_count(g, name, hops=HOPS):
    return g.query(f"MATCH p=(u:Service)-[:DEPENDS_ON*1..{hops} {{kind:'sync'}}]->(:Service {{name:$n}}) "
                   "RETURN count(DISTINCT u)", {"n": name}).result_set[0][0]


def analyse(eco, snap, load, edges_fn, top=15):
    E = edges_fn(snap)
    n = len(snap["packages"])
    dependents, count = reverse_reach(E)
    cands = sorted(dependents)                                    # every package that anything depends on: exact ranking
    t = time.time()
    scored = sorted(((count(x), x) for x in cands), reverse=True)
    ranked = [dict(package=x, reach=c, share=round(c / n, 4), direct=len(dependents[x])) for c, x in scored[:top]]
    for name in REAL[eco]:
        if name in snap["packages"] and all(r["package"] != name for r in ranked):
            c = count(name)
            ranked.append(dict(package=name, reach=c, share=round(c / n, 4), direct=len(dependents[name])))
    bfs_s = time.time() - t
    g = get_graph(f"hijack_{eco}")
    try:
        g.delete()
    except Exception:
        pass
    g = get_graph(f"hijack_{eco}")
    load(g, snap)
    t = time.time()
    for r in ranked:
        r["falkordb_reach"] = cypher_count(g, r["package"])
        r["agrees"] = r["falkordb_reach"] == r["reach"]
        r["note"] = REAL[eco].get(r["package"], "")
    q_s = time.time() - t
    g.delete()
    return dict(ecosystem=eco, packages=n, hops=HOPS, top=ranked, bfs_seconds=round(bfs_s, 1), cypher_seconds=round(q_s, 1),
                all_agree=all(r["agrees"] for r in ranked))


def main():
    from backend.world import npm, pypi
    out = []
    ps = pypi.load_snapshot()
    out.append(analyse("pypi", ps, lambda g, s: pypi.load_pypi(g, s, since_ts=10**12, with_optional=False), lambda s: pypi.edges(s, "sync")))
    ns = npm.load_snapshot()
    slim = dict(ns, packages={k: dict(v, releases=[]) for k, v in ns["packages"].items()})      # the walk needs no releases
    out.append(analyse("npm", slim, npm.load_npm, npm.edges))
    with open("bench/results/hijack_radius.json", "w") as fh:
        json.dump(out, fh, indent=1)
    for e in out:
        print(f"\n{e['ecosystem']}: {e['packages']} packages, within {e['hops']} hops; FalkorDB agrees with BFS: {e['all_agree']}")
        for r in e["top"]:
            print(f"  {r['package']:28s} {r['reach']:6d} packages ({100 * r['share']:.1f}%)  direct {r['direct']:5d}  {r['note']}")


if __name__ == "__main__":
    main()
