# Handoff notes (read this first in every new session)

Project: Blast Radius for Graph Hacks (Oct 15 00:01 - Oct 18 23:59 IST; submit by Sun 18:00 IST). Owner: Neha. Full plan: docs/DESIGN.md. Plain-language tour: docs/ARCHITECTURE.md.

## State (update at the end of every run)
- Built and tested (108 tests): world, failure model, scenarios (dev/test frozen), tools, ranking, board + citation check, memory, verify, sandboxes, MCP server, rule policy, Claude policy (fake-model tested only), API + SSE, React UI, benchmark harness (graph-rules / graph-llm / docs-llm), deploy files, docs skeletons.
- NOT done: real-API run (no key yet), re-recorded replay, final benchmark (Sat night, test split only with --final), BENCHMARK.md numbers, blog numbers, deployment (Neha's accounts Sat), submission.
- Blockers on Neha: (1) Anthropic API key with spend limit; (2) repo must be added to the session's sources so `git push` works (403 until then; everything is committed locally and re-sent as a zip).

## Standing rules
- Never run ranking/agents/benchmark on bench/scenarios/test.json before the Sat-night final.
- Commit small with the attribution lines; try `git push -u origin main` once per run, never force-push.
- Message Neha in simple words; end every run by scheduling the next send_later ~2h out.
- Do not work around the sandbox network policy (openrouter.ai is blocked).

## Extra features: ALL FOUR BUILT AND TESTED (117 tests). Remaining: wire Ripple into API/UI if time; add graph-coverage-only to the final benchmark run. Original list:
1. Ablation condition C: graph tools WITHOUT rank_root_causes (separates graph traversal from our algorithm). Add to bench/run.py as `graph-noranker`.
2. "Multiple causes" clustering: rank candidates per connected cluster of alerting services; report up to two causes when clusters are independent.
3. Ripple: when a late alert arrives mid-investigation, re-run only findings whose receipts read the affected nodes.
4. Import a real system from docker-compose.yml (parse services, depends_on, networks -> Service nodes and DEPENDS_ON edges).
Globex in the benchmark and explore_graph already exist.
Each needs tests; clustering/Ripple must not change the frozen dev/test scenarios' expected answers without an explicit note in docs/ARCHITECTURE.md.
