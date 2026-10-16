# Blast Radius

> **Six alerts at 3 AM. None of them is the problem.**

![Demo: break something, five agents walk the graph, the silent culprit is found with receipts](docs/demo.gif)

Blast Radius is a team of AI agents that investigates outages by walking a company's **dependency graph in FalkorDB**. The real cause is often a quiet database one hop below everything that is on fire, with no alert of its own. The agents find it, **prove every claim with a graph receipt**, and **test the fix on a copy of the graph** before a human approves it.

Built for Graph Hacks (WeMakeDevs x FalkorDB). Tracks 01 (Agents That Act on Connected Data) and 02 (Agent Memory and Coordination).

## What makes it different

| | |
|---|---|
| **Finds silent culprits** | Ranks every service by how well its failure explains the alerts *and* predicts nothing that is not alerting (coverage x precision over sync paths). Unmonitored stores are first-class suspects. |
| **Five agents, one shared board, inside the graph** | Changes, Impact, History and People work in parallel; their findings are Finding nodes linked to Hypothesis nodes. The Lead's only view is a graph query over that board. |
| **No claim without a receipt** | The server rejects any finding that cites a node the agent never read. Each finding stores the exact tool calls, parameters and graph version. Click it in the UI and the nodes it read light up. |
| **Fix simulated before approval** | `GRAPH.COPY` the graph, apply the proposed rollback/restart, re-run the failure model: "clears 13 of 14 alerts". A human presses Approve. |
| **It remembers** | Resolving writes Incident, Resolution and Lesson nodes. Break the same thing again and the History agent cites what you fixed a minute ago. |
| **Late alerts (Ripple)** | A new alert after the verdict retires only the findings whose receipts it touches; everything else is kept without re-running. |
| **Knows when to say "I don't know"** | When two things broke at once it answers "undetermined" and offers both leads instead of guessing. |
| **Ask the graph** | Type any question ("who should I page about ledger-db right now?"). A small model answers using only read-only graph tools; citations to nodes it never read are dropped, and the receipt shows every query. |
| **Bring your own system** | Paste a `docker-compose.yml`: services become nodes, `depends_on` becomes edges, no healthcheck means unmonitored. Break your own architecture and watch the agents work. |
| **Fact-checked words** | Every service name, deploy id, incident id and number in a verdict, a finding or an Ask answer is checked against the tool results that agent actually read. The UI shows "✓ Fact-checked" or lists what could not be found. |
| **An Auditor that only reads the graph** | A sixth agent shares nothing with the team but the graph: it reads the stored Decision, its BLAMES edges, the board's findings, the stored simulation and fact-check, runs deterministic checks (independent support, deploy before first alert, fix clears most alerts, abstentions stay low-confidence), and writes an Audit node. |
| **Postmortem from memory** | After resolving, one click renders a postmortem (timeline, cause, evidence, hypotheses ruled out, lesson saved) purely from the investigation's nodes. No model writes it, so it cannot invent anything. |
| **Real topology too** | Besides two synthetic companies, the `boutique` world is the service graph of Google's open-source Online Boutique microservices demo (monitoring flags, teams and history are our synthetic additions). |
| **Scales** | Exact branch-and-bound ranking: about 0.4 s for a 28-alert storm in a 2,000-service graph and under 2 s at 10,000 services, same top 5 as scoring everyone ([docs/SCALE.md](docs/SCALE.md)). |
| **Honest benchmark** | Graph agents vs. a docs-only agent with the same facts as Markdown + BM25 search, on 20 held-out scenarios frozen before any test run. See [docs/BENCHMARK.md](docs/BENCHMARK.md). |

**Try it:** press *Break something at random* (the culprit is hidden from you and the agents), then *Investigate*. Click any service to see what would break if it failed. Every visitor gets a private copy of the company graph.

## Why FalkorDB

| Role | How the graph is used |
|---|---|
| Dependency reasoning | Variable-length sync paths `-[:DEPENDS_ON*0..6 {kind:'sync'}]->` for coverage and blast radius; async edges for lag |
| Graph algorithms | `algo.pageRank` and `algo.betweenness` for critical services |
| Simulation | `GRAPH.COPY` to a scratch graph, apply the fix, re-run the failure model, drop the copy |
| Isolation | One `GRAPH.COPY` sandbox per visitor (2 h TTL, capped), so anyone can break the company safely |
| Coordination | Investigation, Hypothesis, Finding, Decision nodes; the Lead's only view of its team is a graph query |
| Memory | Incident, Resolution and Lesson nodes written on resolve and read back by the History agent; the postmortem is a traversal |
| Provenance | Findings link to every node they cite; receipts store tool, parameters and graph version; Ripple finds stale findings by traversal |
| Search | Full-text index on incident summaries for similar incidents |

Remove FalkorDB and there is no ranking, no board, no memory, no sandbox and no simulation.

**Also an MCP server:** the same 11 graph tools work from Claude Desktop or any MCP client: `python -m mcp_server.server` (see [mcp_server/server.py](mcp_server/server.py)).

## How it works (one paragraph)

Alerts arrive. The Lead calls `rank_root_causes` (parameterized Cypher finds who can reach whom; plain Python scores coverage x precision) and writes the top 3 hypotheses to the board. Four specialists run in parallel with tools scoped to their role (`recent_changes`, `blast_radius`, `similar_incidents`/`lessons_for`, `find_experts`) and write findings with citations. The Lead reads the board from the graph, decides or abstains, simulates the fix on a graph copy, and drafts a message for Discord. Plain-language tour: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md). Full design: [docs/DESIGN.md](docs/DESIGN.md).

**Cost:** about $0.008 per investigation with Claude (Sonnet 5.5 lead, Haiku 5.5 specialists), about 8x cheaper than the docs-only baseline on the dev scenarios.

## Reproduce every number

| Claim | Command | Write-up |
|---|---|---|
| graph agents vs docs-only, held-out | `python -m bench.run --split test --condition graph-llm --final` (and `docs-llm`, `graph-rules`, `graph-coverage-only`; `--split extended` for the 60-scenario set) | [docs/BENCHMARK.md](docs/BENCHMARK.md) |
| practice-split smoke test | `python -m bench.run --split dev --condition graph-llm` | [docs/BENCHMARK.md](docs/BENCHMARK.md) |
| ranking at 2,000 / 10,000 services | `python -m bench.scale --services 2000` | [docs/SCALE.md](docs/SCALE.md) |
| pruning never changes the top 5 | `pytest backend/tests/test_ranking.py -k branch` | |
| scenario files are frozen | `pytest backend/tests/test_failure_model.py -k frozen` | |

The held-out runner refuses to run without `--final`, and the scenario files are checked against their generator by a test, so nobody can tune on them by accident.

## Run the tests

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
pytest backend/tests
```

Tests use the embedded `falkordblite` by default. To test against a real server set `FALKORDB_URL=redis://localhost:6379` (CI uses the `falkordb/falkordb` Docker image).

## Run the web screen

```bash
uvicorn backend.app.main:app --port 8000      # API
cd frontend && npm install && npm run dev      # UI on http://localhost:5173 (proxies /api)
```

## Windows note

`falkordblite` (the embedded database) does not run on Windows, so on Windows use a FalkorDB server instead and set `FALKORDB_URL`:

```powershell
docker run -p 6379:6379 falkordb/falkordb        # needs Docker Desktop
$env:FALKORDB_URL = "redis://localhost:6379"
pytest backend/tests
```

No Docker? Create a free instance at FalkorDB Cloud and use its connection string as `FALKORDB_URL`.

## AI assistance disclosure

This project was built by Neha Sharma with Claude (Anthropic) as a coding assistant: Claude wrote most of the code, tests and documentation from Neha's design and decisions, and Neha reviewed, tested and directed the work. At runtime the agents use Claude models (Sonnet 5.5 lead, Haiku 5.5 specialists) through the Anthropic API; without a key the app falls back to a deterministic rule policy, so the demo never depends on the model. All benchmark numbers come from the scripts listed above, never from a model's text.

## License

MIT, see [LICENSE](LICENSE).

