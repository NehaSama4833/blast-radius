# Blast Radius

> Six alerts at 3 AM. None of them is the problem.

A team of AI agents that investigates outages by following a company's dependency graph in FalkorDB. Every claim points to the graph path that proves it. Full plan: [docs/DESIGN.md](docs/DESIGN.md). Plain-language explanation: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

Hackathon: Graph Hacks (WeMakeDevs x FalkorDB). Tracks 01 (Agents That Act on Connected Data) and 02 (Agent Memory and Coordination).

## Status

Day 1 done: schema, deterministic world generator, failure model, frozen scenarios, read tools, root-cause ranking (117 tests). Rule-based investigation runner and web API done. Web UI (React + Cytoscape) works against the API. Claude-backed agents are written and tested with a fake model; real-API tuning waits for the key.

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
