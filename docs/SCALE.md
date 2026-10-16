# Scale check

How fast is root-cause ranking on a much bigger company than our demo worlds? Synthetic layered graphs (edge -> api -> core -> data), storms caused by a random silent data store. `rank_root_causes` uses an exact branch-and-bound (precision <= 1 bounds each candidate's best possible score), tested to give the same top 5 as scoring every candidate.

## 2,000 services, 5,262 dependency edges

Loading the graph: 0.1 s. Median of 5 runs per query, embedded FalkorDB on one CPU.

| storm | alerting services | rank_root_causes (ms) | true cause ranked #1 | blast_radius (ms) |
|---|---|---|---|---|
| 1 | 28 | 405.5 | yes | 2.0 |
| 2 | 29 | 413.5 | yes | 1.9 |
| 3 | 29 | 872.0 | yes | 2.0 |
| 4 | 20 | 427.1 | yes | 1.8 |
| 5 | 1 | 56.0 | yes | 1.2 |

Ties are possible in random graphs (two services with identical dependents), so #1 can miss even with perfect data.

## 10,000 services, 26,198 dependency edges

Loading the graph: 0.9 s. Median of 5 runs per query, embedded FalkorDB on one CPU.

| storm | alerting services | rank_root_causes (ms) | true cause ranked #1 | blast_radius (ms) |
|---|---|---|---|---|
| 1 | 14 | 1724.0 | yes | 2.1 |
| 2 | 15 | 1897.9 | yes | 2.6 |
| 3 | 16 | 1593.7 | yes | 2.2 |
| 4 | 23 | 1802.0 | yes | 2.1 |
| 5 | 26 | 1662.0 | yes | 1.9 |


Reproduce: `python -m bench.scale --services 2000` and `--services 10000`. Before the branch-and-bound, the 2,000-service case took 3.0 to 4.1 s per ranking.
