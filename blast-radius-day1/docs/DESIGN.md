# Blast Radius: Design Doc (v2)

> Planning document, written on Oct 14 before the hackathon started. No project code existed before Oct 15, 00:01 IST.

> **Six alerts at 3 AM. None of them is the problem.**
>
> Blast Radius is a team of AI agents that investigates outages by following a company's graph in FalkorDB. It answers five questions: what's *really* broken, what changed, who to call, what worked last time, and what to do now. Every claim it makes points to the graph path that proves it.

Hackathon: Graph Hacks (WeMakeDevs × FalkorDB), Oct 15 00:01 to Oct 18 23:59 IST.
Tracks: entering **01: Agents That Act on Connected Data** (lead pitch) and **02: Agent Memory and Coordination**. The FAQ confirms one project can enter one, two, or all three tracks, each with its own prize. **03: Company Brain** is a partial fit (who owns and knows what, decisions traced to sources); enter it too if the submission form makes that cheap. The README and video should make the 01 and 02 stories explicit.

---

## 0. What "genuinely good" means here

These rules decide close calls during the build.

| Principle | In practice |
|---|---|
| **The graph computes, the LLM judges** | Reachability, scores, ARR sums, and time windows come from Cypher and tested Python. The model decides what to investigate and how to weigh evidence, and never does arithmetic. |
| **Honest** | Every claim cites graph nodes, and code (not the prompt) checks the citations. Every result carries a receipt. The agent says "not sure" when the evidence is weak. The benchmark reports real numbers, failures included, measured on held-out scenarios. No statistic goes into the README, video, or blog unless it's verified at its primary source. |
| **Useful beyond the demo** | It solves a real on-call problem. The same tools work in Claude Desktop through MCP. |
| **Reliable live** | Each visitor gets an isolated sandbox graph. Rate limits, a daily spend cap, and a replay fallback keep the site working during judging. |
| **Safe** | No free-text input on the public site, so there's nothing to prompt-inject. All queries are parameterized. Ad-hoc Cypher runs through `GRAPH.RO_QUERY`, so the database itself rejects writes. External actions need a human click. Secrets live only in env vars. |
| **Neha can explain all of it** | `ARCHITECTURE.md` grows with the code, plus a short walkthrough every day. |

---

## 1. The story

During a real outage, many services alert at once, and the actual cause is often one that **isn't alerting**, such as a database with no monitor or a cache that degrades quietly. Engineers burn precious minutes chasing the loudest symptom. (Any statistic about this goes into public materials only after it's verified at the primary source.)

Blast Radius receives the alert storm and:

1. **Finds the hidden culprit.** A graph algorithm ranks every service by how well "this broke" explains the exact pattern of alerts (§4).
2. **Investigates in parallel.** Four specialist agents (Impact, Changes, History, People) test the top hypotheses, each from its own angle.
3. **Coordinates through the graph.** The agents never talk to each other. They read hypotheses from the graph and write findings back to it, and the Lead decides by reading that shared board.
4. **Acts, with a human in the loop.** It produces a ranked plan ("roll back deploy d-482"), **checks the fix on a copy of the graph before suggesting it**, names who to page (awake now, and with context), and drafts the incident post. One click posts it to a real Discord channel.
5. **Learns.** Resolving an incident stores a Lesson. The next similar storm is solved faster, and the agents cite the lesson.

### Coverage of the brief

| "Work the graph has to do" (hackathon page) | How Blast Radius does it |
|---|---|
| Follow connections across data | Root-cause ranking, blast radius, and change correlation are all multi-hop traversals |
| Remember across sessions | Incidents, resolutions, and Lessons persist, and the History agent retrieves them |
| Share state between agents | Agents coordinate only through `Hypothesis` and `Finding` nodes |
| Connect people, projects, and decisions | People ↔ teams ↔ services ↔ changes ↔ incidents ↔ decisions |
| Show the path behind an answer | Every claim cites nodes, the UI highlights the path, and the reasoning itself is stored in the graph |

---

## 2. Graph model

### Graphs (tenancy)

| Graph name | Purpose |
|---|---|
| `acme` | Template world 1: a payments company, about 30 services |
| `globex` | Template world 2: a logistics company, about 15 services with a different shape, so the agent can't be tuned to one topology |
| `sbx_<id>` | Per-visitor sandbox, created with `GRAPH.COPY` from a template, TTL 2 h, capped in number |
| `bench_<scenario>` | One fresh copy per benchmark scenario, so scenarios never leak into each other |

### Nodes

**Company world (semantic memory)**

| Label | Key properties |
|---|---|
| `Service` | `name`, `layer` (edge/api/core/data), `tier` (1–3), `language`, `monitored` (bool; `false` means it can fail silently) |
| `Feature` | `name` (Checkout, Refunds, …) |
| `Customer` | `name`, `plan` (enterprise/pro/free), `arr` |
| `Team` | `name`, `channel` |
| `Person` | `name`, `handle`, `timezone`, `on_call` (bool) |
| `Commit` | `sha`, `message`, `ts` |
| `Deploy` | `id`, `ts`, `kind` (code/config/infra), `summary`, `diff` |
| `Runbook` | `title`, `steps` |

**Events and history (episodic memory)**

| Label | Key properties |
|---|---|
| `Alert` | `id`, `ts`, `signal` (error_rate/latency/saturation/lag), `severity` |
| `Incident` | `id`, `title`, `summary` (full-text indexed), `severity`, `started_at`, `resolved_at` |
| `Resolution` | `summary`, `action` (rollback/config/scale/hotfix/restart), `ttr_min` |
| `Investigation` | `id`, `ts`, `status`, `model`, `tokens`, `duration_ms` |

**Agent coordination (shared working memory)**

| Label | Key properties |
|---|---|
| `Agent` | `name` (Lead/Impact/Changes/History/People) |
| `Hypothesis` | `id`, `rank`, `structural_score`, `status` (open/supported/weakened/accepted/rejected) |
| `Finding` | `id`, `kind` (structural/temporal/historical/impact/people), `text`, `weight` |
| `Decision` | `root_cause`, `confidence` (high/medium/low), `reasons`, `actions` (JSON) |

**Learned procedures (procedural memory)**

| Label | Key properties |
|---|---|
| `Lesson` | `pattern`, `fix`, `times_seen`, `last_seen`, `avg_ttr_min` |

### Relationships

```
(Service)-[:DEPENDS_ON {kind: "sync"|"async"}]->(Service)
(Feature)-[:USES]->(Service)          (Customer)-[:USES]->(Feature)
(Service)-[:OWNED_BY]->(Team)         (Person)-[:MEMBER_OF]->(Team)
(Person)-[:AUTHORED]->(Commit)-[:TOUCHES]->(Service)
(Deploy)-[:INCLUDES]->(Commit)        (Deploy)-[:TO]->(Service)
(Person)-[:SHIPPED]->(Deploy)         (Runbook)-[:FOR]->(Service)
(Alert)-[:ON]->(Service)
(Incident)-[:AFFECTED]->(Service)     (Incident)-[:CAUSED_BY]->(Deploy|Service)
(Incident)-[:RESOLVED_BY]->(Resolution)
(Person)-[:RESPONDED_TO]->(Incident)

(Investigation)-[:TRIGGERED_BY]->(Alert)
(Investigation)-[:CONSIDERS]->(Hypothesis)-[:ABOUT]->(Service)
(Agent)-[:WROTE]->(Finding)
(Finding)-[:SUPPORTS|WEAKENS]->(Hypothesis)
(Finding)-[:CITES]->(any node)
(Investigation)-[:CONCLUDED]->(Decision)-[:BLAMES]->(Service|Deploy)
(Investigation)-[:BECAME]->(Incident)

(Lesson)-[:ABOUT]->(Service)          (Lesson)-[:LEARNED_FROM]->(Incident)
```

### Memory types (the Track 02 story)

| Memory type | Lives in |
|---|---|
| Semantic: how the company works | Services, dependencies, owners, features, customers |
| Episodic: what happened | Alerts, Incidents, Resolutions, Investigations |
| Procedural: what to do | Runbooks + Lessons learned from resolutions |
| Shared working memory: agents mid-task | Hypotheses + Findings on the current Investigation |

---

## 3. The synthetic world

A deterministic generator (fixed random seed) builds each template world, so every run and test sees the same company.

**Acme Pay** has four layers. Names are illustrative:
- **edge:** `web-gateway`, `mobile-bff`, `partner-api`
- **api:** `payments-api`, `refunds-api`, `orders-api`, `accounts-api`, `payouts-api`, `search-api`, `notifications-api`
- **core:** `ledger-svc`, `fraud-svc`, `pricing-svc`, `auth-svc`, `risk-engine`, `fx-rates`, `kyc-svc`, …
- **data:** `ledger-db`, `orders-db`, `accounts-db`, `redis-cache`, `kafka`, `search-index`, …

The topology mixes sync and async edges, includes a few heavily shared services (such as `auth-svc`, which almost everything depends on), and has some data stores with `monitored: false`. It also has 6 teams, about 18 people across IST, CET, and PST (so "who's awake" matters), about 8 features, about 25 customers with ARR, about 90 days of commits and deploys, and about 25 past incidents with resolutions.

**Planted, recurring patterns** for the History agent to find, for example:
- A `ledger-db` connection-pool config change → pool exhaustion → 5xx across the payments cluster → fixed by rolling back the config.
- A `kafka` partition rebalance → consumer lag in async dependents → fixed by scaling consumers.
- An `auth-svc` certificate rotation → auth failures everywhere → fixed by redeploying the cert.

All timestamps are generated relative to "now" at seed or copy time, so "deployed 41 minutes ago" is always true in the live demo.

### Failure model (single source of truth)

The chaos button, the benchmark, and the tests all use the same function, `break_service(world, service, change_kind, noise)`:
1. Creates a triggering `Deploy` on the broken service, 20–60 minutes before the first alert.
2. Every service with a **sync** path to it fails and alerts, if `monitored`. **Async** dependents get delayed lag alerts.
3. The broken service alerts only if it is monitored. This is how the culprit stays hidden.
4. Optional noise: one unrelated flaky alert, one missing alert (a monitoring gap), and distractor deploys on plausible but innocent services.
5. Returns the ground truth: the root-cause service, the triggering deploy, and the impacted features.

---

## 4. Root-cause ranking: the algorithm at the heart

A good root-cause candidate **explains every failing service** and **doesn't predict failures that aren't happening**. That second condition is what stops a shared service like `auth-svc` from always winning just because everything depends on it.

For each candidate service *c* reachable from the alerting set over sync `DEPENDS_ON` edges:

- **explains(c):** alerting services with a sync path to *c*, plus *c* itself if it is alerting
- **predicts(c):** *c* and all monitored services with a sync path to *c*, meaning everything that *should* be alerting if *c* broke
- **coverage** = |explains| / |alerting|. How much of the storm *c* accounts for.
- **precision** = |explains| / |predicts|. How many of *c*'s predicted failures are actually happening.
- **structural score** = F1(coverage, precision). Ties go to a silent (`monitored: false`) candidate deeper in the stack, which is the classic hidden cause.

Then come two independent kinds of corroboration, gathered by specialists rather than baked into the score:
- **Temporal (Changes agent):** a deploy to *c* or its config inside the window before the first alert.
- **Historical (History agent):** past incidents or Lessons with the same pattern on *c*.

The Lead reports confidence as **high, medium, or low, with the reasons**, for example "explains 6/6 alerts, config deploy 41 min before, same pattern as INC-112." It doesn't invent percentages.

Reachability comes from Cypher, and scoring happens in plain, unit-tested Python:

```cypher
// which alerts each candidate explains (sync edges only)
UNWIND $alerting AS name
MATCH (a:Service {name: name})-[:DEPENDS_ON*0..6 {kind: 'sync'}]->(c:Service)
RETURN c.name AS candidate, collect(DISTINCT a.name) AS explains

// what a candidate predicts
MATCH (u:Service {monitored: true})-[:DEPENDS_ON*1..6 {kind: 'sync'}]->(c:Service {name: $candidate})
RETURN collect(DISTINCT u.name) AS predicts
```

If no candidate explains at least 70% of alerts, the result is reported as "likely more than one cause," and candidates are ranked per connected cluster of alerting services (stretch goal).

**Example output:** `ledger-db explains 6 of 6 alerts. If it failed, 7 monitored services should alert; 6 do (the 7th, audit-svc, is the reported missing alert). auth-svc also explains 6 of 6 but would break 19 services, and 13 of those are healthy.`

---

## 5. The agent team

```
Alert storm ─▶ Lead: triage with rank_root_causes ─▶ writes top Hypotheses to the graph
                         │
      ┌───────────┬──────┴─────┬────────────┐    run in parallel, each reads the
    Impact     Changes      History      People   Hypotheses from the graph
      └───────────┴──────┬─────┴────────────┘
                         ▼  each writes Findings (SUPPORTS / WEAKENS, CITES) to the graph
            Lead: reads the board from the graph ─▶ Decision + ranked actions
                         ▼
     Human: Approve & post to Discord · Mark resolved ─▶ Resolution + Lesson saved
```

| Agent | Job | Main tools |
|---|---|---|
| **Lead** | Triage, dispatch, read the board, decide, propose actions | `rank_root_causes`, `read_board`, `record_decision`, `propose_action` |
| **Impact** | What breaks: failing now vs. at risk soon (async), features, customers, ARR at risk | `blast_radius`, `critical_services` |
| **Changes** | What changed on each hypothesis and its neighborhood, before the storm | `recent_changes`, `change_details` |
| **History** | Matching past incidents and Lessons, plus what fixed them and how fast | `similar_incidents`, `lessons_for` |
| **People** | Who to page: the author of the suspect change, the owning team's on-call, past resolvers, and who's awake right now | `find_experts` |

**Shared rules**
- Specialists only see the graph. The Lead's final prompt is built from a **graph query of the board**, never from specialist transcripts. That's what makes "the graph is the shared state" literally true.
- Write tools are scoped by the server, not by the model. A specialist can only attach findings to its own investigation under its own name.
- **Citation check:** the server records every node ID each tool returned during the investigation. A finding or decision that cites an ID the agent never saw is rejected with an error, so the agent must fix it. The UI shows "claims verified: 14/14".
- **Receipts:** every Finding and Decision stores the tool, its parameters, the graph version, and the IDs of the nodes it read. Any answer can be traced and re-run, and an investigation can be resumed in a later session.
- **Knowing when to abstain:** if no hypothesis is both structurally strong and corroborated, the Lead says so ("low confidence: more than one cause, or missing data") and names what would settle it, instead of guessing.
- Step and token budgets per agent, low temperature, and prompt caching for system prompts and tool definitions.
- Models are set by env vars: `LEAD_MODEL` (default `claude-sonnet-5-5`) and `AGENT_MODEL` (default `claude-haiku-5-5`). Verify the current model IDs on Day 2.
- Target: a full investigation in under 60 s, measured and reported.

### Tools (one registry, also served over MCP)

| Tool | Answers | Notes |
|---|---|---|
| `rank_root_causes(alerting)` | Which service best explains this storm | §4 |
| `blast_radius(service)` | Failing now vs. at risk, features, customers, ARR | ARR summed per distinct customer |
| `dependencies(service)` | What a service relies on | Variable-length traversal |
| `recent_changes(services, window)` | Deploys and commits on these services and their sync dependencies | Time window relative to the first alert |
| `change_details(deploy_id)` | Diff summary, author, included commits | |
| `find_experts(service, at_time)` | Owner, on-call, change authors, past resolvers, awake now | Timezone-aware |
| `similar_incidents(service, text)` | Past incidents on this service or its neighborhood, plus fixes | Full-text index + structural match |
| `lessons_for(service)` | Learned patterns and fixes | Procedural memory |
| `critical_services()` | Chokepoints and most central services | `algo.betweenness`, `algo.pageRank` |
| `path_between(a, b)` | How two things connect, used for explanations | `shortestPath` in `RETURN` |
| `verify_mitigation(action)` | Would this fix clear every alert? | Sandbox copy + failure-model re-run (see "Prove the fix") |
| `explore_graph(cypher)` | Escape hatch for questions no tool covers | `GRAPH.RO_QUERY` + timeout + row limit |
| `add_finding`, `propose_action`, `record_decision` | Agent writes | Scoped and citation-checked |
| `record_resolution` | Memory write-back | UI and human only |

**MCP:** the same registry is served by an MCP server (streamable HTTP + stdio), so Claude Desktop or Claude Code can investigate a graph too. Agents call tools through an MCP client if that stays fast and simple; otherwise they call the same functions directly with the same schemas.

### Prove the fix

Before a mitigation is recommended, `verify_mitigation` checks it: copy the investigation's graph (`GRAPH.COPY`), apply the action (roll back the deploy, fail over the database, scale consumers), re-run the failure model, and confirm that every current alert would clear. Anything left unexplained is reported, for example "rollback clears 6 of 6 alerts; notifications lag needs about 10 min to drain." The UI labels this honestly as a simulation against the dependency graph. In production, the real confirmation is watching the alerts clear.

---

## 6. Benchmark: does the graph actually help?

**Question:** with the *same facts* and the *same model*, does a graph-backed agent find root causes better than a typical "documents + search" agent?

- **Scenarios:** generated by the failure model across both worlds, with known ground truth. Three difficulty tiers:
  - *easy:* single alert, direct cause
  - *medium:* storm with a silent culprit two or more hops down
  - *hard:* storm + flaky noise alert + missing alert + distractor deploys
  - *ambiguous:* a few two-cause storms, where the right answer is "more than one cause"
- **No tuning on the test set:** 10 **dev** scenarios for prompt tuning, 20 **held-out test** scenarios for the reported numbers. Both sets are committed to the repo *before* the test run.
- **Conditions:**
  - **A. Blast Radius:** the full graph agent team
  - **B. Docs-only:** the same facts rendered as Markdown (service catalog pages listing dependencies, team pages, deploy log, postmortems), with `search_docs` (BM25) and `read_doc` tools, and the same step and token budget
  - **C. Ablation, if time allows:** graph tools without `rank_root_causes`, to separate "graph traversal" from "our algorithm"
- **Metrics:** root cause top-1 and top-3, triggering deploy identified, invalid citations, correct abstentions, calibration (are "high confidence" verdicts right more often than "low" ones?), latency, tokens. Results are broken down by tier.
- **Reporting:** `docs/BENCHMARK.md` and a results page in the UI, with every scenario listed, failures included and explained. `make bench` reruns everything.

Memory write-back is disabled during the benchmark, since the baseline has none, which keeps the comparison fair.

---

## 7. Live demo: "Break it yourself"

- **Chaos panel:** pick a service and a change type (config/code/infra) from lists, or press **Surprise me** for a hard scenario. There's no free text anywhere on the public site.
- Each visitor gets a **sandbox graph** (`GRAPH.COPY` of the template, TTL 2 h, max ~50 live sandboxes). Judges don't collide, and memory stays per visitor, so a judge can resolve an incident and then watch the next one use the Lesson.
- **Protection:** per-IP rate limit, a global daily investigation cap, and a **replay fallback** that plays back a recorded real investigation (clearly labeled "replay") if the cap or the API is unavailable.
- **Real action:** **Approve & post** sends the incident report to a Discord channel through a webhook (URL kept in env vars, rate-limited). The UI shows "Posted to #incidents ✓".

---

## 8. UI

- **Graph canvas:** a stable left-to-right layered layout (Cytoscape.js + dagre), so highlighted paths are easy to follow and nodes don't move between steps. Alerting services pulse red, the suspected culprit glows, and each agent highlights the nodes it touched in its own color.
- **Agent lanes:** five columns streaming each step live, such as "Changes: config deploy d-482 to ledger-db, 41 min before the first alert."
- **Hypothesis board:** candidates with coverage/precision, plus findings for and against.
- **Verdict card:** root cause and confidence reasons, impact (now vs. at risk, ARR), who to page and why, ranked actions with precedent, the drafted message, and **Approve & post** and **Mark resolved** buttons.
- **Click any claim** to highlight its evidence path on the graph.
- **History:** replay any past investigation straight from the graph.
- **Benchmark page** and a **world switcher** (Acme / Globex / your sandbox).
- Dark theme by default (it looks good on video) with accessible contrast. Laptop-first, but usable on a phone.

---

## 9. Architecture

```
React + Vite + TS UI ──SSE──▶ FastAPI ──▶ Agent runner (Lead + 4 specialists, Claude API)
   graph canvas · lanes            │                 │
   verdict · chaos · bench         │                 ▼
                                   │        Tool registry (Cypher + schemas) ──▶ FalkorDB
                                   │                 ▲                         (templates,
                                   └─ Discord webhook └── MCP server             sandboxes, bench)
```

```
blast-radius/
  backend/
    app/        FastAPI routes, SSE streaming, rate limits
    graph/      FalkorDB connection, schema, indexes, sandbox management
    tools/      tool registry: each tool = parameterized Cypher + JSON schema
    agents/     lead, specialists, prompts, citation checker, budgets
    world/      world generator, failure model, scenario generator
    actions/    Discord webhook
    tests/      pytest against a real FalkorDB
  mcp_server/
  frontend/
  bench/        generate, run (A/B/C), report
  docs/         DESIGN.md, ARCHITECTURE.md, BENCHMARK.md, blog draft
  docker-compose.yml      local: falkordb + backend + frontend
  .github/workflows/ci.yml
```

- **Stack:** Python 3.12+, FastAPI, `falkordb` client, `anthropic` SDK, `mcp` SDK, pytest; React + Vite + TypeScript + Tailwind + Cytoscape.js.
- **Local dev and tests:** `falkordblite`, an embedded FalkorDB that is pip-installable with no Docker needed, or the `falkordb/falkordb` Docker image. CI runs tests against the Docker image.
- **Deploy:** FalkorDB Cloud (check free-tier memory and that `GRAPH.COPY` is allowed), backend on Render or Railway (Docker), frontend on Vercel.
- **Env vars:** `ANTHROPIC_API_KEY`, `LEAD_MODEL`, `AGENT_MODEL`, `FALKORDB_URL`, `DISCORD_WEBHOOK_URL`, `DAILY_INVESTIGATION_CAP`, `ALLOWED_ORIGINS`. Only `.env.example` goes in the repo.

---

## 10. Plan

### Priorities

| Must ship | Should ship | Could ship |
|---|---|---|
| World + failure model + tools + root-cause ranking, with tests | Chaos button with per-visitor sandboxes | Globex world in the benchmark |
| Lead + 4 specialists coordinating via the graph | Discord action | Ablation (condition C) |
| Citation check, receipts, abstention, memory write-back | MCP server usable from Claude Desktop | "Multiple causes" clustering |
| UI: graph highlighting, lanes, verdict | Replay fallback, CI, `verify_mitigation` | `explore_graph` escape hatch |
| Deployed + benchmark (A vs. B) + README + video | | Import a real system from `docker-compose.yml` |
| | | **Ripple:** when a new or late alert arrives mid-investigation, re-run only the findings whose receipts read the affected nodes |

### Schedule

| Day | Build | Neha |
|---|---|---|
| **Thu 15** | Repo + CI, schema, world generator, failure model, all read tools + `rank_root_causes` with golden tests, scenario generator | Claude API key **by tonight**, with a spend limit set in the Anthropic Console |
| **Fri 16** | Agent team, board in the graph, citation check, memory write-back, SSE API, sandboxes, MCP server | Start Docker, run it locally, 20-min walkthrough |
| **Sat 17** | UI, Discord, deploy by **afternoon**, rate limits + replay fallback, benchmark harness + **run it Saturday night** | FalkorDB Cloud, Render, Vercel accounts; Discord server + webhook |
| **Sun 18** | Benchmark write-up, polish, README, ARCHITECTURE.md, blog draft. **Feature freeze 12:00 IST.** | Record the demo video, publish the blog, **submit by 18:00 IST** |

### Cut rules
- If the agent team isn't solid by Friday midnight, Saturday morning goes to agents, and the UI shrinks to graph + verdict.
- If the benchmark can't run 20 test scenarios, report fewer and say so. Never skip it and never fudge it.
- If deploying fights us past Saturday 18:00, ship the local Docker setup + video, which the rules allow, and keep the replay version hosted.

---

## 11. Demo script (≤ 3 min)

Numbers below are placeholders. The real ones come from the actual run.

1. **(0:00)** "Six alerts at 3 AM. None of them is the problem." The Acme graph, calm.
2. **(0:15)** The alert storm fires and six services pulse red.
3. **(0:25)** Lead triage: "`ledger-db` explains all 6 alerts and predicts nothing we don't see. `auth-svc` also explains them, but would break 13 healthy services." The hidden culprit glows.
4. **(0:50)** Four agents light up the graph in parallel, each in its color: Changes finds a config deploy 41 min ago; History finds INC-112, the same pattern, fixed by rollback in 6 min; People suggests the deploy's author and the past resolver who's awake now; Impact shows Checkout + Refunds, 12 enterprise customers, ARR at risk.
5. **(1:30)** Verdict: high confidence with three reasons, 14/14 claims verified, and the fix checked on a copy of the graph ("rollback clears 6 of 6 alerts"). Click a claim to see its path.
6. **(1:50)** **Approve & post** → the message appears in Discord. **Mark resolved** → a Lesson is saved.
7. **(2:05)** A second, related storm. History now cites the Lesson learned a minute ago. Memory, visibly.
8. **(2:20)** Benchmark: graph agent vs. docs-only on 20 held-out scenarios, by difficulty.
9. **(2:40)** The live site: "Break it yourself. Every visitor gets their own copy of the company graph."
10. **(2:55)** Close: the graph doesn't just store the context, it does the reasoning.

---

## 12. Judging talking points

- **The graph is the reasoning:** root-cause ranking is set coverage over dependency paths, something flat retrieval can't do reliably. The benchmark measures that claim instead of asserting it.
- **Multi-agent coordination through the graph:** agents coordinate only via Hypothesis and Finding nodes, so the whole investigation is auditable.
- **Explainable by construction:** citations are checked by code, and every claim has a clickable path.
- **Memory that changes behavior:** resolved incidents become Lessons that the next investigation uses.
- **Uses FalkorDB's strengths:** variable-length traversals, betweenness and PageRank, `shortestPath`, full-text index, `GRAPH.COPY` multi-tenancy, `GRAPH.RO_QUERY` safety, MCP.
- **Built to be trusted:** human approval for actions, no injection surface, held-out evaluation, tests + CI.

---

## 13. Risks

| Risk | Mitigation |
|---|---|
| Agent output varies between runs | The deterministic algorithm does the core work; low temperature; record the video from a good run; the benchmark reports variance honestly |
| The benchmark shows only a small gain | Report it truthfully, with per-tier analysis of where graphs help and where they don't. Still valuable, and makes a better blog post |
| API cost during judging | Smaller model for specialists, prompt caching, daily cap, replay fallback, Console spend limit |
| FalkorDB Cloud free-tier limits | Cap live sandboxes, TTL cleanup, keep worlds small |
| Too much scope | Priorities and cut rules in §10; feature freeze Sunday noon |
| Neha can't explain parts of it | ARCHITECTURE.md written as we go, plus daily walkthroughs |

---

## 14. FalkorDB features: verified on Oct 14

Tested against FalkorDB `graph` module v4.18.3 (embedded via `falkordblite` 0.10.0):

| Feature | Result |
|---|---|
| Variable-length paths `*0..n`, and property filters on them (`{kind:'sync'}`) | ✅ works |
| `shortestPath` | ✅ only inside `WITH` or `RETURN`, not as `MATCH p = shortestPath(...)` |
| `algo.pageRank('Service','DEPENDS_ON')` | ✅ works |
| `algo.betweenness({nodeLabels, relationshipTypes})` | ✅ works, and found the planted chokepoint |
| `algo.BFS`, `algo.WCC` | ✅ works |
| Full-text index `db.idx.fulltext.createNodeIndex` / `queryNodes` | ✅ works |
| `GRAPH.COPY` (Python `graph.copy()`) | ✅ works; writes to the copy don't touch the original |
| `GRAPH.RO_QUERY` rejects writes | ✅ works, so it's a real safety guarantee |
| Parameterized queries | ✅ works |

Still to check on deploy day: the same features on FalkorDB Cloud's free tier, and its memory limit.
