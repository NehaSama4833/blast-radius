"""Benchmark runner.  python -m bench.run --split dev --condition graph-rules

SAFETY: the held-out TEST split is refused unless --final is given, so nobody (including me) tunes on it by accident.
Condition "graph-rules" is condition A with the no-LLM rule policy (a floor, and a no-API-key sanity check).
Conditions "graph-llm" and "docs-llm" (A and B with a real model) need an API key; both use the same lead model.
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


def _scenario_graph(spec):
    world, o = materialize(spec)
    name = "bench_" + spec["id"].replace("-", "_")
    drop_graph(name)
    g = get_graph(name)
    load_world(g, world, now=NOW)
    failure.apply_outcome(g, o, NOW)
    return world, o, g, name


def run_graph_llm(spec, client=None):
    """Condition A with Claude (needs a key)."""
    from backend.agents.llm_policy import LLMPolicy
    world, o, g, name = _scenario_graph(spec)
    try:
        pol = LLMPolicy(client=client)
        res = run_investigation(g, o.alerting, now=NOW, policy=pol)
        res["tokens"] = sum(v["input"] + v["output"] for v in pol.usage.values())
        res["cost_usd"] = pol.cost_usd()
        return o.truth, res
    finally:
        drop_graph(name)


def run_docs_llm(spec, client=None):
    """Condition B: docs-only baseline (needs a key)."""
    from bench.baseline import run_docs_agent
    world, o = materialize(spec)
    return o.truth, run_docs_agent(world, o, NOW, client=client)


def run_graph_coverage_only(spec):
    """Ablation C: the same graph tools and rule policy, but the ranker scores candidates by coverage alone (no precision / F1).
    It separates "walking the graph" from "our scoring formula". Tool-level patch, bench only; runs are sequential."""
    from functools import partial
    from backend.tools import registry
    orig = registry.TOOLS["rank_root_causes"]["fn"]
    registry.TOOLS["rank_root_causes"]["fn"] = partial(orig, mode="coverage")
    try:
        return run_graph_rules(spec)
    finally:
        registry.TOOLS["rank_root_causes"]["fn"] = orig


CONDITIONS = {"graph-rules": run_graph_rules, "graph-coverage-only": run_graph_coverage_only, "graph-llm": run_graph_llm, "docs-llm": run_docs_llm}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", choices=["dev", "test", "extended"], default="dev")
    ap.add_argument("--condition", choices=sorted(CONDITIONS), default="graph-rules")
    ap.add_argument("--final", action="store_true", help="required to touch the held-out test split")
    ap.add_argument("--out", default=None)
    a = ap.parse_args(argv)
    if a.split in ("test", "extended") and not a.final:
        sys.exit(f"refusing to run the held-out {a.split} split without --final (it must not be used for tuning)")
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
