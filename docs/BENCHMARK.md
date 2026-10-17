# Benchmark: does the graph help?

## Question
Given the same alert storm, does an agent team that works through a dependency graph in FalkorDB find the real root cause more often, and with fewer unsupported claims, than an agent that only has the same facts as documents and keyword search?

## Setup (fixed before any test run)
- **Worlds:** two synthetic companies (acme, ~30 services; globex, ~15), generated deterministically. Some data stores are unmonitored on purpose (hidden culprits), teams span time zones, and there are planted patterns (a past incident that repeats, a misleading recent deploy).
- **Scenarios:** 10 dev scenarios (used for building and tuning) and 20 held-out test scenarios, committed in `bench/scenarios/` before any test run. Tiers: easy, medium, hard, ambiguous (two real causes; the right answer is to say "undetermined"). Test split: 4 easy, 6 medium, 8 hard, 2 ambiguous.
- **Extended held-out split (added Oct 16, frozen before any held-out run):** 60 more scenarios from the same failure model with a new seed, over three worlds: acme 30, globex 20, and boutique 10 (the real Google Online Boutique service topology, a world no rule or prompt was ever tuned on). Because the worlds are small, root services repeat across scenarios (17 distinct root sets); scenarios differ in change kind, noise, distractor deploys and missing or flaky alerts. Run once with `--final`, like the test split. SHA-256 of the scenario files at freeze: dev `55f1f1c2…`, test `c2e69089…`, extended `c7b79e84…`.
- **Conditions:**
  - A `graph-llm`: Lead (Sonnet 5.5) plus four specialists (Haiku 5.5) using graph tools, citation check, fix simulation.
  - B `docs-llm`: same Lead model, same facts as Markdown (services, teams, deploy log, postmortems, runbooks, active alerts), BM25 `search_docs` and `read_doc`. No graph traversal, no ranking, no simulation, no memory.
  - Floor `graph-rules`: graph tools with a deterministic no-LLM policy.
  - Ablation `graph-coverage-only`: same as graph-rules but candidates ranked by coverage alone (no precision), to separate "walking the graph" from "our scoring formula".
- Memory write-back is OFF in all conditions (B has no memory, so this keeps it fair).

## Metrics
Top-1 and top-3 root cause, triggering deploy identified, invalid citations, fact-check flags (names or numbers in the agents' words that no tool returned) (claims with no real evidence behind them), correct and wrong abstentions on ambiguous cases, calibration (is "high" right more often than "medium"), latency, tokens and cost.

## Rules that keep it honest
1. The test and extended splits are run once each, after prompts are frozen, with `make bench` (the runner refuses the test split without `--final`).
2. Whatever the result is gets published, including cases where B wins.
3. Failures are listed per scenario, not hidden in an average.

## Results
Final held-out runs, Sat Oct 17 2026 (one run per condition, `--final`, no code changed between runs). Top-1 is over single-cause scenarios (test: 18 of 20; extended: 55 of 60); the rest are two-cause "ambiguous" scenarios, where the right answer is to abstain.

**Test split (20 scenarios, held out)**

| Condition | Top-1 | Top-3 | Deploy found | Invalid citations | Wrong abstentions | Correct abstentions | Cost (total / per run) | Mean latency |
|---|---|---|---|---|---|---|---|---|
| A graph-llm | 0.833 (15/18) | 1.000 | 0.778 | 3 | 2 | 2/2 | $0.157 / $0.008 | 13.2 s |
| B docs-llm | **0.944 (17/18)** | 0.944 | **0.944** | 0 | 1 | 1/2 | $1.389 / $0.069 | 16.3 s |
| graph-rules (floor, no LLM) | 0.889 (16/18) | 1.000 | 0.889 | 0 | 0 | 2/2 | $0 | 0.14 s |
| graph-coverage-only (ablation) | 0.722 (13/18) | 0.778 | 0.722 | 0 | 0 | 2/2 | $0 | 0.13 s |

**Extended split (60 scenarios, held out; docs-llm not run for cost)**

| Condition | Top-1 | Top-3 | Deploy found | Invalid citations | Wrong abstentions | Correct abstentions | Cost | Mean latency |
|---|---|---|---|---|---|---|---|---|
| A graph-llm | 0.873 (48/55) | 0.982 | 0.818 | 0 | 1 | 5/5 | $0.466 | 11.9 s |
| graph-rules (floor) | 0.873 | 0.982 | 0.873 | 0 | 0 | 5/5 | $0 | 0.12 s |
| graph-coverage-only | 0.727 | 0.855 | 0.727 | 0 | 0 | 5/5 | $0 | 0.13 s |

By tier on the test split (top-1): easy graph-llm 0.75 / docs-llm 1.00 / rules 1.00; medium 1.00 / 1.00 / 1.00; hard 0.75 / 0.875 / 0.75. On the extended split (graph-llm and graph-rules identical): easy 1.00, medium 1.00, hard 0.731 (26 scenarios).

### What this says, plainly
- **The docs-only agent was more accurate than our graph agent on the test split** (top-1 0.944 vs 0.833; 3 scenarios apart on n=18, which is a small, noisy difference). We do not claim the graph agent is more accurate. The docs agent also abstained wrongly once and missed one of two ambiguous cases.
- **The graph agent was about 9x cheaper per investigation** ($0.008 vs $0.069) and slightly faster (13.2 s vs 16.3 s mean).
- **The graph agent made 3 invalid citations on the test split** (the docs agent, which cites documents, had none). The server's citation check rejects these before they are stored; they are counted here because the agent attempted them. It made 0 on the extended split.
- **The LLM did not beat the deterministic no-LLM policy.** graph-rules matched or beat graph-llm on both splits (test 0.889 vs 0.833; extended 0.873 vs 0.873) at zero cost. Most of the accuracy comes from the graph ranking, not the model.
- **Ranking by coverage x precision matters:** coverage-only is clearly worse (0.722 test, 0.727 extended) than graph-rules.
- **Where everything struggles:** hard scenarios (0.73 to 0.88 top-1). On the extended split, all of the misses are hard scenarios or two-cause cases, and 5 of 7 single-cause misses are in the `boutique` world, the one no rule or prompt was tuned on.
- Total spend for all final runs: about $2.01 (graph-llm $0.157 + $0.466, docs-llm $1.389).

Per-scenario results, including every miss, are in `bench/results/test-*.json` and `bench/results/extended-*.json`.

## Dev-split results with the real model (Oct 15; practice scenarios only, NOT the evidence)
Prompts were still being fixed during this run, so treat it as a smoke test.

| Condition | Top-1 (9 single-cause) | Deploy found | Ambiguous abstained | Invalid citations | Avg cost / investigation |
|---|---|---|---|---|---|
| A graph-llm (Sonnet 5.5 lead, Haiku 5.5 specialists) | 9/9 | 9/9 | 1/1 | 0 | about $0.008 |
| B docs-llm (Sonnet 5.5, BM25 docs) | 9/9 | 9/9 | 1/1 | 0 | about $0.068 |

What this says honestly: on the dev scenarios the docs-only baseline is just as accurate. The graph version was about 8x cheaper and every claim cites graph nodes, but accuracy did not separate the two here. Only the held-out test split (more hard cases) can say more, and we will report it whichever way it goes. We will not change scenarios after seeing this.

## Limits to state plainly
Synthetic data we generated ourselves; 20 test scenarios is a small sample; the failure model and the graph tools share assumptions about how failures propagate, which favours the graph condition; one model family.
