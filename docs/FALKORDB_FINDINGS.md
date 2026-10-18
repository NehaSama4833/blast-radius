# What we found when we tested FalkorDB itself

Blast Radius trusts FalkorDB for every answer it gives. If a traversal silently drops a service, the agents
blame the wrong thing and the receipts still look valid. So we tested the database the same way we test our own
code: a **differential fuzzer** (`bench/fuzz_falkordb.py`) builds thousands of small random graphs, runs each
query or algorithm in FalkorDB, and compares the answer with an independent reference (NetworkX, or a brute-force
enumeration in Python for path semantics).

```bash
python -m bench.fuzz_falkordb --graphs 2000 --seed 20261017   # about 70 s, writes bench/results/fuzz_falkordb.json
python -m bench.falkordb_repros                               # the three minimal reproductions below
```

Tested on FalkorDB **4.18.3** (embedded `falkordblite` 0.10.0). CI runs the reproductions against the
`falkordb/falkordb:latest` server too (`backend/tests/test_falkordb_findings.py`).

## Results: 2,000 random graphs, seed 20261017

| What we checked | Reference | Runs | Differences |
|---|---|---:|---:|
| `-[:E*lo..hi]->` without a path variable (path counts) | brute-force trails | 2000 | **549** (226 return the wrong *set of nodes*) |
| `p=()-[:E*lo..hi]->()` with a path variable | brute-force trails | 2000 | **366** (25 wrong set of nodes) |
| `-[:E*1..]->` unbounded reachability | NetworkX | 2000 | 0 |
| `shortestPath()` length | NetworkX BFS | 2000 | 0 |
| `algo.BFS` | NetworkX BFS | 2000 | 0 |
| `algo.WCC` | NetworkX | 2000 | 0 |
| `algo.pageRank` (graphs without parallel edges or self loops) | NetworkX | 1579 | 0 |
| `algo.betweenness` (graphs with at least one edge) | NetworkX (exact) | 1849 | **1406** |
| `algo.SPpaths` weighted shortest path | NetworkX Dijkstra | 2000 | 0 |
| `algo.MSF` total weight (graphs with at least one edge) | NetworkX | 1849 | 0 |
| our own exact betweenness (`backend/tools/centrality.py`) | NetworkX | 2000 | 0 |

Up to 8 examples of each kind of difference are stored, with graph and query, in `bench/results/fuzz_falkordb.json`
(rerun the fuzzer to get all of them). We shrank them by hand and with a delta-debugging loop to the three cases
below. Each is 3 or 4 nodes. `algo.betweenness` is sampled, so its count changes a little from run to run (1,413 on
a rerun with the same seed); the other counts are deterministic.

## F1. A bounded variable-length pattern without a path variable misses reachable nodes

```cypher
CREATE (a:N {name:'a'}), (b:N {name:'b'}), (c:N {name:'c'}), (d:N {name:'d'})
CREATE (a)-[:E]->(b), (a)-[:E]->(c), (b)-[:E]->(c), (c)-[:E]->(d)

MATCH (:N {name:'a'})-[:E*1..2]->(t:N) RETURN t.name ORDER BY t.name
-- expected: b, c, c, d      (a->b, a->c, a->b->c, a->c->d)
-- got:      b, c, c          (d is missing, though a->c->d has length 2)
```

- It is a DAG: no cycles and no repeated nodes are involved.
- The same query with a path variable (`MATCH p=...`) returns the right answer, and so does the untyped pattern
  `-[*1..2]->`. A property filter on the relationship (`-[:E*1..2 {kind:'sync'}]->`) also returns the right answer.
- Our guess: when the path is not needed, the traversal keeps a visited set. Node `c` is first reached at the depth
  limit (a->b->c), marked visited, and so not expanded when it is reached again at depth 1 (a->c), so `d` is never found.
- `count(*)` and `RETURN DISTINCT` are wrong the same way, so "how many services are within 2 hops" is wrong too.

## F2. A path is never extended past a node it has already visited

```cypher
CREATE (a:N {name:'a'}), (b:N {name:'b'}), (c:N {name:'c'}), (d:N {name:'d'})
CREATE (a)-[:E]->(b), (b)-[:E]->(c), (c)-[:E]->(b), (b)-[:E]->(d)

MATCH p=(:N {name:'a'})-[:E*4]->(t:N) RETURN [x IN nodes(p) | x.name]
-- expected: [a, b, c, b, d]   (four different relationships)
-- got:      no rows
```

- With `*3` FalkorDB returns `[a, b, c, b]`, so a repeated node is allowed as the *last* hop, but the path is never
  extended after it. A self loop behaves the same: with `a->b, b->b, b->c`, `a-[*1..3]->` misses `a->b->b->c`.
- openCypher only forbids using the same relationship twice in one path; nodes may repeat. This affects both named
  and unnamed patterns. In a separate run (`--graphs 1500 --seed 99`), a brute-force reference that adds this rule ("a path is
  never extended from a node it has already visited") reproduced FalkorDB exactly in all 259 named-pattern
  differences.

## F3. `algo.betweenness` is a sampled estimate even when the exact answer is cheap

```cypher
CREATE (:N {name:'a'})-[:E]->(:N {name:'b'})-[:E]->(:N {name:'c'})

CALL algo.betweenness({nodeLabels:['N'], relationshipTypes:['E'], samplingSize: 300, samplingSeed: $s})
YIELD node, score WHERE node.name = 'b' RETURN score
-- expected: 1.0 for every seed (exactly one shortest path, a to c, passes through b)
-- got:      0.0, 1.0 or 2.0 depending on samplingSeed
```

- On random graphs the default call (no sampling parameters) differs from the exact answer in 1,406 of the 1,849 graphs that have edges.
- This looks like source nodes being drawn with replacement, even when `samplingSize` is larger than the graph.
  If sampling is intended, we suggest computing exactly when `samplingSize >= node count`, and documenting that the
  score is an unscaled estimate.

## Smaller quirks (not counted as findings)

- `algo.pageRank` counts parallel edges once (NetworkX counts each). A reasonable choice; we skip those graphs.
- `algo.pageRank` sometimes leaves isolated nodes out of the result.
- `algo.BFS` returns no row, rather than an empty list, when nothing is reachable.
- `algo.MSF` and `algo.betweenness` raise an error if the relationship type does not exist yet (an empty graph).
- `RETURN [x IN nodes(p) | x.name] ORDER BY length(p)` raises an internal error
  (`_AR_EXP_UpdateEntityIdx: Unable to locate a value with alias p`) instead of a user-facing message.

## What it meant for Blast Radius

| Finding | Affected us? | What we did |
|---|---|---|
| F1 | **No.** Every bounded pattern we run has a property filter (`{kind:'sync'}`) or a path variable. | `test_our_query_shapes_are_not_affected_by_f1` runs our exact query shapes on 80 random DAGs where the depth limit binds, against a brute-force reference, and also checks that the unsafe shape does go wrong there (so the test has teeth). |
| F2 | **No.** Service dependency graphs are acyclic. | Documented. An imported docker-compose file with a dependency cycle could be affected. |
| F3 | **Yes.** `critical_services` (what the What-if panel and the agents use to say "this is a chokepoint") ranked by `algo.betweenness`. | Replaced with an exact Brandes implementation over the edges read from FalkorDB (`backend/tools/centrality.py`, checked against NetworkX on 2,000 graphs). PageRank still comes from FalkorDB. |

F1 and F2 reproduce on 4.18.3; on the latest server image used in CI they no longer reproduce. F3 still does.

The three reproductions are `xfail` tests that assert the correct answer. F1 and F2 are non-strict, so they may
pass on newer servers; F3 is `xfail(strict=True)`, so when a FalkorDB release fixes it, CI fails and tells us to
update this page.

## Draft issue for FalkorDB

> **Title:** Variable-length traversal drops valid paths (unbound typed pattern on a DAG; paths through a repeated node)
>
> FalkorDB 4.18.3. Two minimal graphs (4 nodes each) are in the body above (F1 and F2), with expected results under
> openCypher relationship-uniqueness semantics. F1 is the more serious: on an acyclic graph,
> `MATCH (:N {name:'a'})-[:E*1..2]->(t) RETURN t` misses a node at distance 2 unless the pattern is bound to a path
> variable or has no type. Found with a differential fuzzer against a brute-force reference (2,000 random graphs:
> 549 differences for the unbound pattern vs 366 with a path variable). Script: `bench/falkordb_repros.py`.
>
> A separate issue for `algo.betweenness` (F3): on a 3-node chain the middle node scores 0, 1 or 2 depending on
> `samplingSeed`, even with `samplingSize: 300`.
