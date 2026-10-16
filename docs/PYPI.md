# The real world: 15,000 Python packages and 1.2 million releases

The company worlds (acme, globex, boutique) are small enough to read. This one is not made up and not small:
it is the **Python package ecosystem**, loaded into FalkorDB from public PyPI metadata, and we replay **21 real
supply-chain incidents** on it: famous releases that broke other packages.

```bash
python scripts/fetch_pypi.py --top 15000          # optional: refresh the snapshot (~75 s); a frozen one is in the repo
python -m bench.pypi_incidents --split dev        # builds the graph (~30 s) and replays 14 incidents x 3 seeds
python -m bench.pypi_incidents --split test       # 7 more incidents x 3 seeds, run once
GRAPH_NAME=pypi python -m mcp_server.server       # the same graph and tools from Claude Desktop (tool: suspect_releases)
```

## The graph

| | Count | Source |
|---|---:|---|
| `(:Service)` packages | 14,997 | the 15,000 most-downloaded PyPI projects ([hugovk/top-pypi-packages](https://github.com/hugovk/top-pypi-packages), list of 2026-10-01; 3 had no metadata) |
| `[:DEPENDS_ON {kind:'sync'}]` required dependencies | 49,786 | each package's current `requires_dist`, both ends in the set |
| `[:DEPENDS_ON {kind:'optional'}]` extras | 47,604 | `pkg[extra]` requirements; loaded but never walked |
| `(:Deploy {kind:'release'})-[:TO]->` releases | 1,193,520 | upload time of every non-yanked release |
| Total | 1.21 M nodes, 1.29 M relationships | about 600 MB in FalkorDB, loads in about 30 s |

Snapshot: `bench/data/pypi_snapshot.json.gz` (10.9 MB, sha256 `5dc534cb5a77cfac…`), fetched 2026-10-16 by
`scripts/fetch_pypi.py`. Only public metadata (names, requirement strings, release times); no package code.

It uses the same schema as the company worlds, so the same Cypher, tools and MCP server work on it unchanged.

## The question

A dozen-plus packages' CI goes red within a few hours. Hundreds of other packages released something in the same
48 hours. **Which release did it?** The tool, `suspect_releases` (`backend/tools/supply_chain.py`), is one Cypher
query:

```cypher
UNWIND $failing AS name
MATCH p=(a:Service {name: name})-[:DEPENDS_ON*0..2 {kind: 'sync'}]->(c:Service)
WITH DISTINCT a, c
MATCH (d:Deploy)-[:TO]->(c) WHERE d.ts >= $t0 AND d.ts <= $t1
WITH c, a, max(d.ts) AS last, collect(d.version) AS versions
RETURN c.name, collect(DISTINCT a.name), max(last), head(versions)
```

It walks from each failing package down its required dependencies, keeps the packages that released something in
the window, and counts how many failures each one can explain (coverage). Ranking: coverage, then F1 (coverage ×
precision), then the newer release. The query shape (path variable, 0 or 1 to 2 hops, a property filter) is one the
FalkorDB fuzzer found correct ([FALKORDB_FINDINGS.md](FALKORDB_FINDINGS.md)), and every run below is also checked
against a plain Python BFS over the same snapshot.

## The incidents

Culprit releases (package, version and upload time are real, from pypi.org):

| Split | Incidents |
|---|---|
| dev (14) | numpy 2.0.0, setuptools 72.0.0, urllib3 2.0.0, cython 3.0.0, pydantic 2.0, markupsafe 2.1.0, protobuf 4.21.0, werkzeug 2.1.0, jinja2 3.1.0, sqlalchemy 2.0.0, pyyaml 6.0, importlib-metadata 5.0.0, packaging 22.0, httpx 0.28.0 |
| test (7) | requests 2.32.0, pillow 10.0.0, pandas 2.0.0, pytest 8.0.0, cryptography 3.4, openai 1.0.0, django 4.0 |

Four of them were later yanked from PyPI; the snapshot skips yanked files, so the benchmark adds those releases back
with their real upload time.

What is **simulated**: which packages fail. For each incident and seed (3 seeds), a random 15 to 50% of the
culprit's direct dependents fail (3 to 40 of them), each failing package sometimes takes one of its own dependents
down too, and up to 5 unrelated packages fail as noise. The first failure comes 1 to 6 hours after the upload.
Scenarios are frozen in `bench/scenarios/pypi_dev.json` and `pypi_test.json`.

## Results

| Method | dev top-1 | dev top-3 | test top-1 | test top-3 |
|---|---:|---:|---:|---:|
| **graph: coverage first** (default) | **40/42** | **42/42** | **21/21** | **21/21** |
| graph: F1 first | 25/42 | 34/42 | 18/21 | 18/21 |
| newest release before the failures | 0/42 | 0/42 | 0/21 | 0/21 |
| most-downloaded package that released | 3/42 | 18/42 | 4/21 | 12/21 |

- On average 41 (dev) and 46 (test) packages were failing and 749 (dev) and 558 (test) releases were in the window.
- Median query time 0.06 s on the full graph. The graph walk matched the Python BFS in 42/42 and 21/21 runs.
- **How the default was chosen, honestly:** both scorings were written before the first run. The dev run showed
  that precision hurts here, so coverage-first became the default. The test split was then run once with it.
  Why precision hurts: a breaking release breaks only *some* of its dependents (many pin versions or never touch
  the changed API), so "most of your dependents are failing" is not a signature here, unlike the company worlds.
- **The two dev misses** are both pydantic 2.0: typing-extensions released in the same 48 hours, and every package
  that depends on pydantic also reaches typing-extensions through it, so it explains at least as many failures.
  The graph cannot separate them; reading the release notes (what the Changes agent does with a diff) can.

## Limits

- Dependency edges are from the snapshot date (2026), not from the incident dates. Packages change requirements
  over time, so some 2021–2024 edges are missing and some are new.
- Which dependents fail is simulated. We did not have the real list of packages each incident broke.
- Only the 15,000 most-downloaded packages are in the graph; a dependency outside that set is not walked.
