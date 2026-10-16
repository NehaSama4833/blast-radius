# Demo script (about 2.5 minutes)

Numbers marked [TBD] come from the final benchmark (Saturday night). Everything else matches the current screen.

1. **Hook (0:00, 10 s).** Opening screen. Say: "Six alerts at 3 AM. None of them is the problem." Point at the map: 30 services of a fake company, stored as a graph in FalkorDB.
2. **Break it (0:10, 15 s).** Press **Break something at random**. Red nodes appear. Say: "I don't know what I just broke, and neither do the agents. Every visitor gets a private copy of this graph."
3. **Investigate (0:25, 40 s).** Press **Investigate**. Point at the five colored lanes and the colored rings on the map: "Each agent reads a different part of the graph: Changes looks for recent deploys, Impact for what breaks and the revenue at risk, History for the same pattern before, People for who is awake." The scoreboard counts graph queries and claims.
4. **Verdict (1:05, 20 s).** Read the amber line: "The culprit never raised an alert of its own." Point at the simulation line: "the fix was tested on a copy of the graph first: it clears N of M alerts." Mention Approve & post: a human always decides.
5. **Proof (1:25, 15 s).** Click a finding on the board. The receipt opens: the exact graph query, its parameters, the graph version, the nodes it read, which light up on the map. "No claim without a receipt. Invented citations are rejected by the server."
6. **Late alert (1:40, 15 s).** Press **⚡ A late alert arrives**. "Only the findings that touched the new alert are redone. The rest are kept."
7. **Memory (1:55, 20 s).** Press **Mark resolved**, then **↻ Same failure again**, then **Investigate**. The blue line: "Remembered: this matches INC-…, which you resolved a moment ago."
8. **Ask + your own system (2:15, 10 s).** Click an example question under the Ask box; show its receipt. Optionally open **+ your docker-compose…** to show any architecture can be loaded.
9. **Close (2:25, 10 s).** Benchmark: graph agents vs a docs-only agent on 20 held-out scenarios: [TBD]. Cost per investigation: about $0.008 (graph) vs about $0.07 (docs, dev estimate). "Break it yourself at [site URL]."
