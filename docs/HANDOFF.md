# Handoff notes (read this first in every new session)

Project: Blast Radius for Graph Hacks (Oct 15 00:01 - Oct 18 23:59 IST; submissions close Sun 18 Oct 23:59 IST (our own target: 18:00 IST, leaving a buffer)). Owner: Neha. Full plan: docs/DESIGN.md. Plain-language tour: docs/ARCHITECTURE.md.

## Oct 17 early (IST 04:00-06:00)
- FalkorDB Cloud instance was gone; Neha is creating a new one (Singapore or Mumbai) and updating FALKORDB_URL on Render.
- Added: /api/ready + wake-up screen + DB socket timeouts; CI frontend job + badge; FalkorDB differential fuzzer with 3 findings (docs/FALKORDB_FINDINGS.md), exact betweenness; PyPI world + 21 real incidents (docs/ECOSYSTEMS.md: 40/42 dev, 21/21 test); Beat-the-agents game. 136 tests + 3 strict xfails.
- Later: npm world (50k packages, 5.5 M releases; full snapshot gitignored, 2.4 MB slice committed; 30/30 held-out). The final-benchmark scheduled task text omits the extended split; follow the plan here: test split 4 conditions + extended split graph-llm/graph-rules/graph-coverage-only.
- The agents' tool registry is unchanged (suspect_releases is MCP-only), so tonight's final benchmark conditions are as planned. critical_services now uses exact betweenness.

## State (update at the end of every run)
- Built and tested (117 tests): world, failure model, scenarios (dev/test frozen), tools, ranking, board + citation check, memory, verify, sandboxes, MCP server, rule policy, Claude policy (fake-model tested only), API + SSE, React UI, benchmark harness (graph-rules / graph-llm / docs-llm), deploy files, docs skeletons.
- Real API key works (stored in /home/claude/.secrets/env.sh, chmod 600; source it before runs). Dev runs done Oct 15: graph-llm 10/10 at ~$0.008/inv, docs-llm 10/10 at ~$0.068/inv (honest: no accuracy gap on dev). Replay re-recorded with Claude. ~$0.80 spent of a $5 budget.
- NOT done: final benchmark (Sat night, test split only with --final), BENCHMARK.md numbers, blog numbers, deployment (Neha's accounts Sat), submission.
- Blockers on Neha: (1) confirm $5 spend limit; (2) repo must be added to the session's sources so `git push` works (403 until then; everything is committed locally and re-sent as a zip).

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

## Oct 15 night: feature work closed
Added: first-glance UI, what-if, late alert (Ripple) in UI, memory "again" moment, Ask the graph, bring-your-own docker-compose, README GIF. 121 tests.
FROM NOW ON: no new features. Remaining = deploy (Sat, Neha's accounts), final benchmark (Sat night: graph-llm, docs-llm, graph-rules, graph-coverage-only on test split with --final, once), BENCHMARK.md/blog numbers, polish, video (Neha, Sun), submissions close Sun 18 Oct 23:59 IST (our own target: 18:00 IST, leaving a buffer).

## Oct 16: from the organizers
Submissions close 11:59 PM IST Oct 18. Side prize: best blog post (write-up of what we built, how it works, what we learned), submitted with the project; top 50 teams get t-shirts.
Blog plan: Sunday morning I write a strong full draft from docs/BLOG_DRAFT.md with the real benchmark numbers and a "what we learned" section; Neha adds her own voice/stories and publishes. Live-site budget: DAILY_INVESTIGATION_CAP=30, then replay.

## Oct 16 afternoon (after competitor review)
Added: extended held-out split (60, frozen, 3 worlds incl. boutique = real Online Boutique topology), fact-check (faithful.py), postmortem from graph, branch-and-bound ranking + docs/SCALE.md, LICENSE, AI disclosure, reproduce table. 126 tests.
FINAL BENCHMARK (Sat night) must run: test split -> graph-llm, docs-llm, graph-rules, graph-coverage-only; extended split -> graph-llm, graph-rules, graph-coverage-only (docs-llm skipped for budget, ~$0.07/inv). Budget left ~$3.5.
