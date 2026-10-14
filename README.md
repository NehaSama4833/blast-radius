# Blast Radius

> Six alerts at 3 AM. None of them is the problem.

A team of AI agents that investigates outages by following a company's dependency graph in FalkorDB. Every claim points to the graph path that proves it. Full plan: [docs/DESIGN.md](docs/DESIGN.md). Plain-language explanation: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

Hackathon: Graph Hacks (WeMakeDevs x FalkorDB). Tracks 01 (Agents That Act on Connected Data) and 02 (Agent Memory and Coordination).

## Status

Day 1 done: schema, deterministic world generator, failure model, frozen scenarios, read tools, root-cause ranking (71 tests). Agents, API and UI come next.

## Run the tests

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
pytest backend/tests
```

Tests use the embedded `falkordblite` by default. To test against a real server set `FALKORDB_URL=redis://localhost:6379` (CI uses the `falkordb/falkordb` Docker image).
