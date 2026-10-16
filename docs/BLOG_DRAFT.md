# Six alerts at 3 AM, none of them the problem

*Draft. Benchmark numbers are filled in only after the final run.*

When an outage hits, the loudest alerts are usually victims. The real cause is often something quiet: a database with no monitoring of its own, one hop below everything that is on fire. Finding it means walking a dependency graph, so we gave a team of AI agents a graph to walk, in FalkorDB, instead of a pile of documents.

## What you see
Press "Break something at random" and a fake company's map turns red. Press "Investigate" and five agents start reading the graph, each in its own color. Changes checks what shipped right before the alerts. Impact works out what would break, which customers are hit and how much revenue is at risk. History looks for the same pattern in past incidents. People finds who knows the system and is awake right now. The Lead ranks suspects, reads the shared board and decides, or says "undetermined" when two things broke at once.

## Why a graph
Root-cause ranking is a graph question: which single service, if it failed, would explain the alerts we see and predict no alerts we do not see? Coverage times precision over dependency paths finds the silent culprit that a keyword search walks past.

The board itself lives in the graph: hypotheses, findings and decisions are nodes, so the Lead's only view of its team is a graph query. Every finding must cite nodes that its agent actually read; the server rejects anything else and stores a receipt with the exact queries and the graph version. Fixes are simulated on a copy of the graph (GRAPH.COPY) before a human approves them. Resolved incidents are written back as Incident, Resolution and Lesson nodes, so the next time the same thing breaks, the History agent cites what you fixed a minute ago. A late alert retires only the findings whose receipts it touches.

## Things you can try
Click any service to see what would break if it failed. Ask the graph a question in plain words and get an answer with receipts. Paste your own docker-compose.yml and break your own architecture.

## How we tested it
Thirty scenarios generated from a deterministic failure model: ten for building, twenty held out and frozen before any test run, across easy, medium, hard and two-cause cases. We compare the graph agents with a docs-only agent that has the same facts as Markdown and keyword search, the same lead model, and no graph. Results: [TBD after the final run], including the cases where the docs-only agent does as well or better.

What we already saw on the practice scenarios: both got every case right, and the graph version was about 8 times cheaper per investigation (about $0.008 vs $0.07). Accuracy did not separate them there; the held-out set has more hard cases.

## Honest limits
Synthetic data we generated ourselves, a small test set, and a failure model that shares assumptions with the graph tools.

## Built with
FalkorDB, Claude (Sonnet 5.5 lead, Haiku 5.5 specialists), FastAPI, React and Cytoscape. MCP server included.
