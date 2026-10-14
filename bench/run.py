"""Benchmark runner.  python -m bench.run --split dev --condition graph-rules

SAFETY: the held-out TEST split is refused unless --final is given, so nobody (including me) tunes on it by accident.
Condition "graph-rules" is condition A with the no-LLM rule policy (a floor, and a no-API-key sanity check).
Conditions "graph-llm" and "docs-llm" (A and B with a real model) are added once the model key is available.
Memory write-back is NOT used here (the docs-only baseline has no memory, so the comparison stays fair).
"""
import argparse
import json
import sys
import time
from pathlib import Path

from bench.metrics import aggregate, score_one
from backend.agents.runner import run_investigation
from backend.graph.db import drop_graph, get_graph
from backend.world import failure
from backend.world.loader import load_world
from backend.world.scenarios import load_specs, materialize

NOW = 1_800_000_000
RESULTS = Path(__file__).resolve().parent / "results"


def run_graph_rules(spec):
    world, o = materialize(spec)
    name = "bench_" + spec["id"].replace("-", "_")        # one fresh graph per scenario: scenarios never leak into each other
    drop_graph(name)
    g = get_graph(name)
    try:
        load_world(g, world, now=NOW)
        failure.apply_outcome(g, o, NOW)
        t0 = time.time()
        res = run_investigation(g, o.alerting, now=NOW)
        res["duration_s"] = round(time.time() - t0, 3)
        res["tokens"] = 0
        return o.truth, res
    finally:
        drop_graph(name)


CONDITIONS = {"graph-rules": run_graph_rules}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", choices=["dev", "test"], default="dev")
    ap.add_argument("--condition", choices=sorted(CONDITIONS), default="graph-rules")
    ap.add_argument("--final", action="store_true", help="required to touch the held-out test split")
    ap.add_argument("--out", default=None)
    a = ap.parse_args(argv)
    if a.split == "test" and not a.final:
        sys.exit("refusing to run the held-out test split without --final (it must not be used for tuning)")
    scored = []
    for spec in load_specs(a.split):
        truth, res = CONDITIONS[a.condition](spec)
        scored.append(score_one(spec, truth, res))
    report = dict(split=a.split, condition=a.condition, summary=aggregate(scored), scenarios=scored)
    RESULTS.mkdir(exist_ok=True)
    path = Path(a.out) if a.out else RESULTS / f"{a.split}-{a.condition}.json"
    path.write_text(json.dumps(report, indent=1))
    s = report["summary"]["all"]
    print(f"{a.condition} on {a.split}: n={s['n']} top1={s['top1']} top3={s['top3']} deploy={s['deploy_found']} "
          f"wrong_abstentions={s['wrong_abstentions']} correct_abstentions={s['correct_abstentions']} invalid_citations={s['invalid_citations']}")
    return report


if __name__ == "__main__":
    main()
