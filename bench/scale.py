"""Scale check: how fast are the graph tools on a much bigger company? (synthetic, layered random DAG)

python -m bench.scale --services 2000      -> prints a latency table (results recorded in docs/SCALE.md)
"""
import argparse
import random
import statistics
import time

from backend.graph.db import drop_graph, get_graph
from backend.tools.ranking import rank_root_causes
from backend.tools.registry import call_tool
from backend.world import failure
from backend.world.loader import load_world

LAYERS = ["edge", "api", "core", "data"]


def make_world(n, seed=7):
    rng = random.Random(seed)
    share = [0.1, 0.3, 0.35, 0.25]
    services, by_layer = [], {l: [] for l in LAYERS}
    for i in range(n):
        layer = rng.choices(LAYERS, share)[0]
        name = f"{layer}-{i:05d}"
        by_layer[layer].append(name)
        services.append(dict(name=name, layer=layer, tier=rng.choice([1, 2, 3]), language="go",
                             monitored=(layer != "data" or rng.random() < 0.4), team=f"team-{i % 40}"))
    deps = set()
    for li, layer in enumerate(LAYERS[:-1]):
        lower = [x for l in LAYERS[li + 1:] for x in by_layer[l]]
        for s in by_layer[layer]:
            for d in rng.sample(lower, k=min(len(lower), rng.randint(2, 5))):
                deps.add((s, d, "async" if rng.random() < 0.1 else "sync"))
    teams = [dict(name=f"team-{i}", channel=f"#t{i}") for i in range(40)]
    people = [dict(name=f"P{i}", handle=f"p{i}", team=f"team-{i % 40}", timezone="UTC", on_call=i < 40) for i in range(120)]
    return dict(name="scale", teams=teams, services=services, deps=[dict(src=a, dst=b, kind=k) for a, b, k in sorted(deps)],
                people=people, features=[], customers=[], runbooks=[], deploys=[], incidents=[], lessons=[])


def timed(fn, reps=5):
    ts = []
    for _ in range(reps):
        t = time.perf_counter(); out = fn(); ts.append((time.perf_counter() - t) * 1000)
    return out, statistics.median(ts)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--services", type=int, default=2000)
    a = ap.parse_args(argv)
    w = make_world(a.services)
    g = get_graph("scale_bench"); drop_graph("scale_bench"); g = get_graph("scale_bench")
    t = time.perf_counter(); load_world(g, w, now=1_800_000_000); load_s = time.perf_counter() - t
    rng = random.Random(1)
    silent = [s["name"] for s in w["services"] if not s["monitored"]]
    rows = []
    for k in range(5):                                     # five storms caused by random silent data stores
        root = rng.choice(silent)
        alerting = sorted(failure.alerting_for(w, [root]))
        if not alerting:
            continue
        r, ms = timed(lambda: rank_root_causes(g, alerting, top_k=5))
        top = r.data["candidates"][0]["candidate"]
        _, br = timed(lambda: call_tool(g, "blast_radius", {"service": root}))
        rows.append(dict(root=root, alerts=len(alerting), rank_ms=round(ms, 1), top1=(top == root), blast_ms=round(br, 1)))
    drop_graph("scale_bench")
    lines = [f"# Scale check ({a.services} services, {len(w['deps'])} dependency edges, synthetic layered graph)", "",
             f"Loading the graph: {load_s:.1f} s. Median of 5 runs per query, embedded FalkorDB on one CPU.", "",
             "| storm | alerting services | rank_root_causes (ms) | true cause ranked #1 | blast_radius (ms) |", "|---|---|---|---|---|"]
    lines += [f"| {i + 1} | {r['alerts']} | {r['rank_ms']} | {'yes' if r['top1'] else 'no'} | {r['blast_ms']} |" for i, r in enumerate(rows)]
    lines += ["", "Ties are possible in random graphs (two services with identical dependents), so #1 can miss even with perfect data.",
              "Reproduce: `python -m bench.scale --services 2000`."]
    print("\n".join(lines))
    return lines


if __name__ == "__main__":
    main()
