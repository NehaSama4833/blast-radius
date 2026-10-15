# Six alerts at 3 AM, none of them the problem (draft)

When an outage hits, the loudest alerts are usually victims. The real cause is often something quiet: a database with no monitoring of its own, one hop below everything that is on fire. Finding it means walking a dependency graph, which is why we gave a team of AI agents a graph to walk in FalkorDB instead of a pile of documents.

## What it does
Four specialists work in parallel on a shared board: Changes (what shipped recently), Impact (what breaks, which features, how much revenue), History (has this pattern happened before), People (who is awake and knows this system). A Lead agent reads the board and decides, or says "undetermined" when two causes are mixed together.

## Why a graph
- Root-cause ranking is a graph question: which single service, if it failed, would explain the alerts we see and predict no alerts we do not see?
- Every claim must cite graph nodes the agent actually read. The server rejects anything else, and each finding keeps a receipt: the exact queries and the graph version.
- Fixes are simulated on a copy of the graph (GRAPH.COPY) before anyone approves them.
- Resolved incidents are written back as memory, so the next investigation starts smarter.

## How we tested it
(Fill in after the final run: setup, numbers, and the cases where the docs-only baseline did better. See docs/BENCHMARK.md.)

## What we would do next
Real telemetry instead of a synthetic world, more failure types, and a feedback loop from on-call engineers.
