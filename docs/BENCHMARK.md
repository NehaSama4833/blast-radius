# Benchmark: does the graph help? (skeleton; numbers filled in only from real runs)

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
_Not run yet._ Dev-only sanity check with the rule policy (written while looking at the dev scenarios, so a plumbing check, not evidence): 9/9 single-cause dev scenarios correct, ambiguous dev scenario correctly abstained.

Budget: the docs-only baseline costs about $0.07 per investigation, so it runs on the 20-scenario test split only; the graph conditions run on test and extended.

| Condition | Top-1 | Top-3 | Deploy found | Invalid citations | Correct abstain | Cost / investigation |
|---|---|---|---|---|---|---|
| A graph-llm | TBD | TBD | TBD | TBD | TBD | TBD |
| B docs-llm | TBD | TBD | TBD | TBD | TBD | TBD |
| graph-rules (floor) | TBD | TBD | TBD | TBD | TBD | $0 |

## Dev-split results with the real model (Oct 15; practice scenarios only, NOT the evidence)
Prompts were still being fixed during this run, so treat it as a smoke test.

| Condition | Top-1 (9 single-cause) | Deploy found | Ambiguous abstained | Invalid citations | Avg cost / investigation |
|---|---|---|---|---|---|
| A graph-llm (Sonnet 5.5 lead, Haiku 5.5 specialists) | 9/9 | 9/9 | 1/1 | 0 | about $0.008 |
| B docs-llm (Sonnet 5.5, BM25 docs) | 9/9 | 9/9 | 1/1 | 0 | about $0.068 |

What this says honestly: on the dev scenarios the docs-only baseline is just as accurate. The graph version was about 8x cheaper and every claim cites graph nodes, but accuracy did not separate the two here. Only the held-out test split (more hard cases) can say more, and we will report it whichever way it goes. We will not change scenarios after seeing this.

## Limits to state plainly
Synthetic data we generated ourselves; 20 test scenarios is a small sample; the failure model and the graph tools share assumptions about how failures propagate, which favours the graph condition; one model family.
