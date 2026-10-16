"""Replay real npm incidents on a real slice of the npm dependency graph. Run once, with the method frozen.

Same protocol as bench/pypi_incidents.py: real packages, real runtime-dependency edges (latest versions, as of the
snapshot), every real publish time, real culprit releases; simulated choice of which dependents fail. The ranking
(`suspect_releases`, coverage first) was fixed on the PyPI dev split before this file existed, so every npm number
is a held-out result.

    python -m bench.npm_incidents                 # needs bench/data/npm_snapshot.json.gz or the committed slice

Incidents whose culprit has fewer than 3 direct runtime dependents in the snapshot are listed as skipped (for example
a package that projects mostly use as a devDependency); we do not walk devDependencies.
"""
import argparse
import gzip
import hashlib
import json
import random
import time
from collections import defaultdict
from datetime import datetime

from backend.graph.db import get_graph
from backend.tools.supply_chain import suspect_releases
from backend.world.npm import DATA, edges, load_npm, load_snapshot
from bench.pypi_incidents import _down, _within, rank_of, releases_in_window, summarize

# (package, version, why). Publish times come from the registry's `time` field in the snapshot.
INCIDENTS = [
    ("colors", "1.4.1", "the maintainer published a sabotaged release that loops forever printing garbage (removed by npm)"),
    ("faker", "6.6.6", "the maintainer published a release with the library's code removed"),
    ("is-promise", "2.2.0", "an `exports` field broke deep imports; create-react-app and Angular builds failed (fixed in 2.2.1)"),
    ("node-ipc", "10.1.1", "protestware: overwrote files on machines with Russian or Belarusian IPs (removed by npm)"),
    ("ua-parser-js", "0.7.29", "hijacked account: release with a crypto-miner and password stealer (removed by npm)"),
    ("event-stream", "3.3.6", "added the flatmap-stream dependency, which carried code that stole bitcoin wallets"),
    ("coa", "2.0.3", "hijacked account: release with malware (removed by npm)"),
    ("chalk", "5.0.0", "became ESM-only; `require('chalk')` stopped working"),
    ("node-fetch", "3.0.0", "became ESM-only; `require('node-fetch')` stopped working"),
    ("uuid", "8.0.0", "removed deep imports such as `require('uuid/v4')`"),
    ("eslint", "9.0.0", "flat config became the default; `.eslintrc` files stopped being read"),
    ("axios", "1.0.0", "first 1.x release; changes to its package exports broke some bundler and test setups"),
]
SEEDS = (1, 2, 3)
GRAPH = "npm_bench"


def culprit_time(snap, pkg, ver):
    return dict(map(tuple, snap["packages"].get(pkg, {}).get("releases", []))).get(ver)


def make_scenarios(snap):
    dependents = defaultdict(set)
    for a, b in edges(snap):
        dependents[b].add(a)
    names = sorted(snap["packages"])
    out, skipped = [], []
    for pkg, ver, why in INCIDENTS:
        t = culprit_time(snap, pkg, ver)
        direct = sorted(dependents[pkg])
        if t is None or len(direct) < 3:
            skipped.append(dict(culprit=pkg, version=ver, reason="not in snapshot" if t is None else f"{len(direct)} direct runtime dependents"))
            continue
        for seed in SEEDS:
            rng = random.Random(f"npm-{pkg}-{ver}-{seed}")
            k = max(3, min(40, int(len(direct) * rng.uniform(0.15, 0.5))))
            failing = set(rng.sample(direct, min(k, len(direct))))
            for f in sorted(failing):
                nxt = sorted(dependents[f] - failing)
                if nxt and rng.random() < 0.3:
                    failing.add(rng.choice(nxt))
            near = _within(dependents, pkg, 3)
            noise = [n for n in rng.sample(names, 60) if n not in near and n != pkg][:rng.randint(2, 5)]
            failing |= set(noise)
            first = t + rng.randint(1, 6) * 3600
            out.append(dict(id=f"{pkg}-{ver}-s{seed}", culprit=pkg, version=ver, released=t, first_failure=first,
                            failing=sorted(failing), noise=sorted(noise), why=why))
    return out, skipped


def run(scenarios, g, snap):
    deps_of = defaultdict(set)
    indeg = defaultdict(int)
    for a, b in edges(snap):
        deps_of[a].add(b)
        indeg[b] += 1
    results = []
    for sc in scenarios:
        at = sc["first_failure"]
        window = releases_in_window(g, at - 48 * 3600, at)
        newest = list(dict.fromkeys(n for n, _, _ in sorted(window, key=lambda r: -r[1])))
        popular = list(dict.fromkeys(n for n, _, _ in sorted(window, key=lambda r: (-indeg[r[0]], r[0]))))
        t = time.time()
        res = suspect_releases(g, sc["failing"], at, window_h=48, hops=2, top_k=len(window) or 5).data
        took = time.time() - t
        cov_rank = [s["package"] for s in res["suspects"]]
        f1_rank = [s["package"] for s in sorted(res["suspects"], key=lambda s: (-s["f1"], -s["coverage"], -s["released_at"], s["package"]))]
        released = {n for n, _, _ in window}
        want = defaultdict(set)
        for f in sc["failing"]:
            for c in _down(deps_of, f, 2):
                if c in released:
                    want[c].add(f)
        got = {s["package"]: s["explains"] for s in res["suspects"]}
        results.append(dict(id=sc["id"], culprit=sc["culprit"], n_failing=len(sc["failing"]), releases_in_window=len(window),
                            ranks=dict(coverage=rank_of(cov_rank, sc["culprit"]), f1=rank_of(f1_rank, sc["culprit"]),
                                       newest=rank_of(newest, sc["culprit"]), popular=rank_of(popular, sc["culprit"])),
                            top3=cov_rank[:3], seconds=round(took, 3), bfs_agrees=got == {c: len(v) for c, v in want.items()}))
    return results


def write_slice(snap, scenarios, path):
    """A small, committable copy: every package and edge, but only releases within 3 days of an incident window."""
    keep = [(s["first_failure"] - 5 * 86400, s["first_failure"] + 86400) for s in scenarios]
    P = {}
    for n, p in snap["packages"].items():
        rel = [r for r in p["releases"] if any(a <= r[1] <= b for a, b in keep)]
        P[n] = dict(latest=p["latest"], deps=p["deps"], releases=rel, removed=[v for v in p.get("removed", []) if v in {r[0] for r in rel}])
    sl = dict({k: v for k, v in snap.items() if k not in ("packages", "_path")}, packages=P, slice_of=hashlib.sha256(
        open(snap["_path"], "rb").read()).hexdigest(), n_releases_full=sum(len(p["releases"]) for p in snap["packages"].values()))
    with gzip.open(path, "wt", encoding="utf-8") as fh:
        json.dump(sl, fh, separators=(",", ":"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--write-slice", action="store_true")
    a = ap.parse_args()
    snap = load_snapshot()
    scenarios, skipped = make_scenarios(snap)
    blob = json.dumps(scenarios, sort_keys=True).encode()
    with open("bench/scenarios/npm.json", "w") as fh:
        json.dump(scenarios, fh, indent=1)
    g = get_graph(GRAPH)
    try:
        g.delete()
    except Exception:
        pass
    g = get_graph(GRAPH)
    t = time.time()
    stats = load_npm(g, snap)
    stats["load_seconds"] = round(time.time() - t, 1)
    results = run(scenarios, g, snap)
    summary = summarize(results)
    report = dict(snapshot=snap["_path"].rsplit("/", 1)[-1], snapshot_fetched_at=snap["fetched_at"], graph=stats,
                  scenarios_sha256=hashlib.sha256(blob).hexdigest(), n_scenarios=len(scenarios), skipped=skipped,
                  summary=summary, results=results)
    with open("bench/results/npm.json", "w") as fh:
        json.dump(report, fh, indent=1)
    if a.write_slice:
        write_slice(snap, scenarios, DATA / "npm_slice.json.gz")
    print(f"snapshot: {report['snapshot']}  graph: {stats}")
    print(f"{len(results)} scenarios, skipped: {skipped}")
    for m in ("coverage", "f1", "newest", "popular"):
        s = summary[m]
        print(f"  {m:9s} top-1 {s['top1']:2d}/{s['n']}  top-3 {s['top3']:2d}/{s['n']}  median rank {s['median_rank']}")
    print(f"  graph walk equals a Python BFS in {summary['bfs_agrees']}/{len(results)}; median query {summary['median_seconds']} s")


if __name__ == "__main__":
    main()
