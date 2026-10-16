# The real world: 65,000 packages and 6.7 million releases

The company worlds (acme, globex, boutique) are small enough to read. These two are not made up and not small:
the **Python** and **JavaScript (npm)** package ecosystems, loaded into FalkorDB from public registry metadata.
On them we replay **31 real supply-chain incidents**: famous releases that broke, sabotaged or hijacked other
packages.

| | PyPI | npm | Total |
|---|---:|---:|---:|
| packages (`:Service`) | 14,997 | 50,000 | **64,997** |
| required dependencies (`DEPENDS_ON {kind:'sync'}`) | 48,766 | 159,667 | **208,433** |
| real releases (`:Deploy`) | 1,193,520 | 5,488,584 | **6,682,104** |
| incidents replayed (x 3 seeds) | 21 | 10 | **31** |
| culprit ranked first | 61/63 | 30/30 | **91/93** |
| ... on runs that were never used to tune anything | 21/21 | 30/30 | **51/51** |

## Part 1: PyPI

```bash
python scripts/fetch_pypi.py --top 15000          # optional: refresh the snapshot (~75 s); a frozen one is in the repo
python -m bench.pypi_incidents --split dev        # builds the graph (~30 s) and replays 14 incidents x 3 seeds
python -m bench.pypi_incidents --split test       # 7 more incidents x 3 seeds, run once
GRAPH_NAME=pypi python -m mcp_server.server       # the same graph and tools from Claude Desktop (tool: suspect_releases)
```

### The graph

| | Count | Source |
|---|---:|---|
| `(:Service)` packages | 14,997 | the 15,000 most-downloaded PyPI projects ([hugovk/top-pypi-packages](https://github.com/hugovk/top-pypi-packages), list of 2026-10-01; 3 had no metadata) |
| `[:DEPENDS_ON {kind:'sync'}]` required dependencies | 48,766 | each package's current `requires_dist`, both ends in the set |
| `[:DEPENDS_ON {kind:'optional'}]` extras | 48,624 | `pkg[extra]` requirements; loaded but never walked |
| `(:Deploy {kind:'release'})-[:TO]->` releases | 1,193,520 | upload time of every non-yanked release |
| Total | 1.21 M nodes, 1.29 M relationships | about 600 MB in FalkorDB, loads in about 30 s |

Snapshot: `bench/data/pypi_snapshot.json.gz` (10.9 MB, sha256 `5dc534cb5a77cfac…`), fetched 2026-10-16 by
`scripts/fetch_pypi.py`. Only public metadata (names, requirement strings, release times); no package code.

It uses the same schema as the company worlds, so the same Cypher, tools and MCP server work on it unchanged.

### The question

Nine to fifty packages' CI goes red within a few hours. Hundreds of other packages released something in the same
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
precision), then the newer release. The query shape (path variable, 0 or 1 to 2 hops, a property filter) is one we check against a
brute-force reference in `test_our_query_shapes_are_not_affected_by_f1` ([FALKORDB_FINDINGS.md](FALKORDB_FINDINGS.md)), and every run below is also checked
against a plain Python BFS over the same snapshot.

### The incidents

Culprit releases (package, version and upload time are real, from pypi.org):

| Split | Incidents |
|---|---|
| dev (14) | numpy 2.0.0, setuptools 72.0.0, urllib3 2.0.0, cython 3.0.0, pydantic 2.0, markupsafe 2.1.0, protobuf 4.21.0, werkzeug 2.1.0, jinja2 3.1.0, sqlalchemy 2.0.0, pyyaml 6.0, importlib-metadata 5.0.0, packaging 22.0, httpx 0.28.0 |
| test (7) | requests 2.32.0, pillow 10.0.0, pandas 2.0.0, pytest 8.0.0, cryptography 3.4, openai 1.0.0, django 4.0 |

Four of them were later yanked from PyPI; the snapshot skips yanked files, so the benchmark adds those releases back
with their real upload time.

What is **simulated**: which packages fail. For each incident and seed (3 seeds), a random 15 to 50% of the
culprit's direct dependents fail (3 to 40 of them), each failing package sometimes takes one of its own dependents
down too, and 2 to 5 unrelated packages fail as noise. The first failure comes 1 to 6 hours after the upload.
Scenarios are frozen in `bench/scenarios/pypi_dev.json` and `pypi_test.json`.

### Results

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

### Limits

- Dependency edges are from the snapshot date (2026), not from the incident dates. Packages change requirements
  over time, so some 2021–2024 edges are missing and some are new.
- Which dependents fail is simulated. We did not have the real list of packages each incident broke.
- Only the 15,000 most-downloaded packages are in the graph; a dependency outside that set is not walked.

## Part 2: npm

```bash
python scripts/fetch_npm.py --max 50000          # ~8 min: the full snapshot (56 MB, not in the repo: too big)
python -m bench.npm_incidents                    # loads 5.5 M releases (~140 s) and replays 10 incidents x 3 seeds
GRAPH_NAME=npm python -m mcp_server.server       # same tools from Claude Desktop
```

**The graph.** Seeds: the 1,000 most popular packages for each of 218 keywords, from npm's own search (133,459
distinct names). Then a crawl that always fetches the dependencies of what it already has before the next seed,
stopping at 50,000 packages, so 159,667 of the 160,022 dependency entries point inside the set (99.8%). For each
package: its latest version's runtime `dependencies` and the publish time of **every** version, including versions
npm later removed (the registry keeps their time; colors 1.4.1 is one). 5,488,584 releases in FalkorDB, loaded in
about 140 s. Release nodes are kept lean (`ts`, `version`, `removed`) because there are 5.5 million of them.

Without the 56 MB snapshot, `bench/data/npm_slice.json.gz` (2.4 MB, committed) has every package and edge but only
the releases within a few days of each incident. The benchmark gives **identical results** on the slice and on the
full snapshot (checked: same scenarios hash, same ranks for all 30 runs). Full snapshot sha256 `89ef153bb7ef7da5…`,
fetched 2026-10-16.

**The incidents** (versions and publish times from the registry):

| Culprit | What happened |
|---|---|
| colors 1.4.1 | the maintainer published a sabotaged release that loops forever printing garbage (removed by npm) |
| is-promise 2.2.0 | an `exports` field broke deep imports; create-react-app and Angular builds failed (fixed in 2.2.1) |
| node-ipc 10.1.1 | protestware that overwrote files on machines with Russian or Belarusian IPs (removed by npm) |
| ua-parser-js 0.7.29 | hijacked account: a release with a crypto-miner and password stealer (removed by npm) |
| event-stream 3.3.6 | added the flatmap-stream dependency, which carried code that stole bitcoin wallets |
| chalk 5.0.0 | became ESM-only; `require('chalk')` stopped working |
| node-fetch 3.0.0 | became ESM-only |
| uuid 8.0.0 | removed deep imports such as `require('uuid/v4')` |
| eslint 9.0.0 | flat config became the default; `.eslintrc` files stopped being read |
| axios 1.0.0 | first 1.x release; changes to its package exports broke some setups |

Skipped, and listed in the results file: faker 6.6.6 (only 2 packages in the set use it as a runtime dependency;
projects mostly use it in tests, and we do not walk devDependencies) and coa 2.0.3 (1).

**Results** (same simulation of failures as PyPI; the ranking was frozen from the PyPI dev split before any npm
run, so all of this is held-out):

| Method | top-1 | top-3 |
|---|---:|---:|
| **graph: coverage first** (default) | **30/30** | **30/30** |
| graph: F1 first | 28/30 | 30/30 |
| newest release before the failures | 0/30 | 0/30 |
| most depended-on package that released | 3/30 | 12/30 |

- On average 31 packages were failing (7 to 52) and **2,636 releases** were published in each 48-hour window.
- Median query time 0.11 s on the full 5.5 M-release graph. The graph walk matched a Python BFS in 30/30 runs.
- Same limits as PyPI: dependency edges are from the snapshot date, which dependents fail is simulated, and only
  runtime dependencies are walked.
