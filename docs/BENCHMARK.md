# Benchmark: does the graph help? (skeleton; numbers filled in only from real runs)

## Question
Given the same alert storm, does an agent team that works through a dependency graph in FalkorDB find the real root cause more often, and with fewer unsupported claims, than an agent that only has the same facts as documents and keyword search?

## Setup (fixed before any test run)
- **Worlds:** two synthetic companies (acme, ~30 services; globex, ~15), generated deterministically. Some data stores are unmonitored on purpose (hidden culprits), teams span time zones, and there are planted patterns (a past incident that repeats, a misleading recent deploy).
- **Scenarios:** 10 dev scenarios (used for building and tuning) and 20 held-out test scenarios, committed in `bench/scenarios/` before any test run. Tiers: easy, medium, hard, ambiguous (two real causes; the right answer is to say "undetermined"). Test split: 4 easy, 6 medium, 8 hard, 2 ambiguous.
- **Conditions:**
  - A `graph-llm`: Lead (Sonnet 5.5) plus four specialists (Haiku 5.5) using graph tools, citation check, fix simulation.
  - B `docs-llm`: same Lead model, same facts as Markdown (services, teams, deploy log, postmortems, runbooks, active alerts), BM25 `search_docs` and `read_doc`. No graph traversal, no ranking, no simulation, no memory.
  - Floor `graph-rules`: graph tools with a deterministic no-LLM policy.
- Memory write-back is OFF in all conditions (B has no memory, so this keeps it fair).

## Metrics
Top-1 and top-3 root cause, triggering deploy identified, invalid citations (claims with no real evidence behind them), correct and wrong abstentions on ambiguous cases, calibration (is "high" right more often than "medium"), latency, tokens and cost.

## Rules that keep it honest
1. The test split is run once, after prompts are frozen, with `make bench` (the runner refuses the test split without `--final`).
2. Whatever the result is gets published, including cases where B wins.
3. Failures are listed per scenario, not hidden in an average.

## Results
_Not run yet._ Dev-only sanity check with the rule policy (written while looking at the dev scenarios, so a plumbing check, not evidence): 9/9 single-cause dev scenarios correct, ambiguous dev scenario correctly abstained.

| Condition | Top-1 | Top-3 | Deploy found | Invalid citations | Correct abstain | Cost / investigation |
|---|---|---|---|---|---|---|
| A graph-llm | TBD | TBD | TBD | TBD | TBD | TBD |
| B docs-llm | TBD | TBD | TBD | TBD | TBD | TBD |
| graph-rules (floor) | TBD | TBD | TBD | TBD | TBD | $0 |

## Limits to state plainly
Synthetic data we generated ourselves; 20 test scenarios is a small sample; the failure model and the graph tools share assumptions about how failures propagate, which favours the graph condition; one model family.
