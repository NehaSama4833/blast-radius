"""Pure-Python helpers over a world dict (no database). Used by the generator, the failure model and tests."""
from collections import deque

LAYER_ORDER = {"edge": 0, "api": 1, "core": 2, "data": 3}


def svc_map(world):
    return {s["name"]: s for s in world["services"]}


def _adj(world, kind, reverse):
    adj = {s["name"]: [] for s in world["services"]}
    for d in world["deps"]:
        if d["kind"] != kind:
            continue
        a, b = (d["dst"], d["src"]) if reverse else (d["src"], d["dst"])
        adj[a].append(b)
    return adj


def sync_dependents(world, service):
    """{name: hops} for every service with a sync path TO `service` (excluding itself)."""
    adj = _adj(world, "sync", reverse=True)
    dist, q = {service: 0}, deque([service])
    while q:
        cur = q.popleft()
        for nxt in adj[cur]:
            if nxt not in dist:
                dist[nxt] = dist[cur] + 1
                q.append(nxt)
    dist.pop(service)
    return dist


def sync_dependencies(world, service):
    adj = _adj(world, "sync", reverse=False)
    dist, q = {service: 0}, deque([service])
    while q:
        cur = q.popleft()
        for nxt in adj[cur]:
            if nxt not in dist:
                dist[nxt] = dist[cur] + 1
                q.append(nxt)
    dist.pop(service)
    return dist


def async_dependents(world, service):
    """Services with a direct async edge to `service`."""
    return sorted(d["src"] for d in world["deps"] if d["kind"] == "async" and d["dst"] == service)


def is_dag(world):
    adj = _adj(world, "sync", reverse=False)
    for d in world["deps"]:
        if d["kind"] == "async":
            adj[d["src"]].append(d["dst"])
    state = {}

    def visit(n):
        if state.get(n) == 1:
            return False
        if state.get(n) == 2:
            return True
        state[n] = 1
        for m in adj[n]:
            if not visit(m):
                return False
        state[n] = 2
        return True

    return all(visit(n) for n in adj)


def max_depth(world):
    return max((max(sync_dependents(world, s["name"]).values(), default=0) for s in world["services"]), default=0)


def features_hit(world, services):
    """Feature names that use any of `services`."""
    sset = set(services)
    return sorted(f["name"] for f in world["features"] if sset & set(f["services"]))
