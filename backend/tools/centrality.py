"""Exact betweenness centrality (Brandes 2001) over edges read from FalkorDB.

Why not algo.betweenness? FalkorDB samples source nodes even when the sample is as large as the graph, so on a
three-node chain the middle node scores 0, 1 or 2 depending on the seed (exact: 1). See docs/FALKORDB_FINDINGS.md.
Our graphs are small (tens to a few thousand services), and Brandes is O(V*E) here, so the exact answer is cheap.
FalkorDB still stores and serves the graph; only this one score is computed in Python.
"""
from collections import defaultdict, deque


def betweenness(nodes, edges):
    """Directed, unnormalised betweenness: for every ordered pair (s, t), the share of shortest s->t paths through v.

    Parallel edges count once and self loops are ignored, as shortest paths never use them."""
    adj = defaultdict(set)
    for a, b in edges:
        if a != b:
            adj[a].add(b)
    score = dict.fromkeys(nodes, 0.0)
    for s in nodes:
        order, preds = [], defaultdict(list)
        sigma = defaultdict(float)
        dist = {s: 0}
        sigma[s] = 1.0
        q = deque([s])
        while q:
            v = q.popleft()
            order.append(v)
            for w in adj[v]:
                if w not in dist:
                    dist[w] = dist[v] + 1
                    q.append(w)
                if dist[w] == dist[v] + 1:
                    sigma[w] += sigma[v]
                    preds[w].append(v)
        delta = defaultdict(float)
        for w in reversed(order):
            for v in preds[w]:
                delta[v] += sigma[v] / sigma[w] * (1 + delta[w])
            if w != s:
                score[w] += delta[w]
    return score
