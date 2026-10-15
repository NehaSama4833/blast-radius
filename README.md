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
| **Honest benchmark** | Graph agents vs. a docs-only agent with the same facts as Markdown + BM25 search, on 20 held-out scenarios frozen before any test run. See [docs/BENCHMARK.md](docs/BENCHMARK.md). |

**Try it:** press *Break something at random* (the culprit is hidden from you and the agents), then *Investigate*. Click any service to see what would break if it failed. Every visitor gets a private copy of the company graph.

**Also an MCP server:** the same 11 graph tools work from Claude Desktop or any MCP client: `python -m mcp_server.server` (see [mcp_server/server.py](mcp_server/server.py)).

## How it works (one paragraph)

Alerts arrive. The Lead calls `rank_root_causes` (parameterized Cypher finds who can reach whom; plain Python scores coverage x precision) and writes the top 3 hypotheses to the board. Four specialists run in parallel with tools scoped to their role (`recent_changes`, `blast_radius`, `similar_incidents`/`lessons_for`, `find_experts`) and write findings with citations. The Lead reads the board from the graph, decides or abstains, simulates the fix on a graph copy, and drafts a message for Discord. Plain-language tour: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md). Full design: [docs/DESIGN.md](docs/DESIGN.md).

**Cost:** about $0.008 per investigation with Claude (Sonnet 5.5 lead, Haiku 5.5 specialists), about 8x cheaper than the docs-only baseline on the dev scenarios.

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
