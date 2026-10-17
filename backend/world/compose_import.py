"""Import a real system from a docker-compose.yml into the dependency graph (design doc: "could ship").

Rules (kept simple and printed back to the user so nothing is hidden):
  * every compose service becomes a Service; `depends_on` becomes a SYNC DEPENDS_ON edge (dependent -> dependency);
  * a service that depends on a message broker image (kafka, rabbitmq, nats, redpanda) gets an ASYNC edge instead;
  * layer is guessed from the image: databases/caches -> data, brokers -> core, services publishing ports -> edge, others -> api;
  * a service with no `healthcheck` is marked monitored:false (we assume nothing alerts on it), so it can be a silent culprit;
  * no teams/people/deploys come from compose; one placeholder team owns everything. Add deploys later with load_deploys.
Use as a library (`compose_to_world`) or `python -m backend.world.compose_import docker-compose.yml --graph mygraph`.
"""
import argparse
import re

import yaml

# Untrusted input from the public site. Names reach Cypher (as parameters), the agents' prompts and Discord, so they
# must look like Docker service names: no spaces, no instructions, no markup (docs/SECURITY.md).
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,62}$")
MAX_SERVICES, MAX_EDGES, MAX_YAML_NODES = 80, 1000, 20000


def _check_size(doc):
    """YAML anchors can make a 20 KB file expand to millions of nodes (a 'billion laughs' bomb). Walk with a budget."""
    budget, stack = MAX_YAML_NODES, [doc]
    while stack:
        x = stack.pop()
        budget -= 1
        if budget < 0:
            raise ValueError("the compose file expands to too much data (YAML anchors?)")
        if isinstance(x, dict):
            stack.extend(x.keys())
            stack.extend(x.values())
        elif isinstance(x, list):
            stack.extend(x)


def _has_cycle(names, deps):
    adj = {n: [] for n in names}
    for d in deps:
        adj[d["src"]].append(d["dst"])
    state = {}
    for start in names:
        if start in state:
            continue
        stack = [(start, iter(adj[start]))]
        state[start] = 1
        while stack:
            v, it = stack[-1]
            nxt = next(it, None)
            if nxt is None:
                state[v] = 2
                stack.pop()
            elif state.get(nxt) == 1:
                return True
            elif nxt not in state:
                state[nxt] = 1
                stack.append((nxt, iter(adj[nxt])))
    return False

DATA = ("postgres", "mysql", "mariadb", "mongo", "redis", "memcached", "elasticsearch", "cassandra", "clickhouse")
BROKER = ("kafka", "rabbitmq", "nats", "redpanda", "pulsar")


def _image(svc):
    return str(svc.get("image", "")).lower()


def _depends(svc):
    d = svc.get("depends_on") or []
    return list(d) if isinstance(d, (list, dict)) else []


def compose_to_world(text, name="imported"):
    try:
        doc = yaml.safe_load(text) or {}
    except yaml.YAMLError as e:
        raise ValueError(f"not valid YAML: {str(e).splitlines()[0][:120]}")
    if not isinstance(doc, dict):
        raise ValueError("no services found in the compose file")
    _check_size(doc)
    svcs = doc.get("services")
    if not isinstance(svcs, dict) or not svcs:
        raise ValueError("no services found in the compose file")
    if len(svcs) > MAX_SERVICES:
        raise ValueError(f"too many services ({len(svcs)}); the limit is {MAX_SERVICES}")
    bad = [str(n)[:40] for n in svcs if not isinstance(n, str) or not NAME_RE.match(n)]
    if bad:
        raise ValueError(f"service names must look like docker service names (letters, digits, . _ -): {bad[:3]}")
    if any(v is not None and not isinstance(v, dict) for v in svcs.values()):
        raise ValueError("each service must be a mapping")
    brokers = {n for n, s in svcs.items() if any(b in _image(s) for b in BROKER) or any(b in n.lower() for b in BROKER)}
    services, deps, notes = [], [], []
    for n, s in sorted(svcs.items()):
        s = s or {}
        img = _image(s)
        if n in brokers:
            layer = "core"
        elif any(d in img or d in n.lower() for d in DATA):
            layer = "data"
        elif s.get("ports"):
            layer = "edge"
        else:
            layer = "api"
        monitored = bool(s.get("healthcheck"))
        services.append(dict(name=n, layer=layer, tier=2, language="unknown", monitored=monitored, team="imported"))
        if not monitored:
            notes.append(f"{n}: no healthcheck, treated as unmonitored")
        for d in _depends(s):
            if not isinstance(d, str) or d not in svcs:
                notes.append(f"{n}: depends_on {d!r} is not a service in this file, skipped")
                continue
            deps.append(dict(src=n, dst=d, kind="async" if d in brokers else "sync"))
    if len(deps) > MAX_EDGES:
        raise ValueError(f"too many depends_on edges ({len(deps)}); the limit is {MAX_EDGES}")
    if _has_cycle([x["name"] for x in services], deps):
        raise ValueError("depends_on has a cycle; docker compose would refuse to start this file too")
    world = dict(name=name, teams=[dict(name="imported", channel="#imported")], services=services, deps=deps,
                 people=[dict(name="You", handle="you", team="imported", timezone="UTC", on_call=True)],   # placeholder owner
                 features=[], customers=[],
                 runbooks=[], deploys=[], incidents=[], lessons=[])
    return world, notes


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("file")
    ap.add_argument("--graph", default="imported")
    a = ap.parse_args(argv)
    from backend.graph.db import drop_graph, get_graph
    from backend.world.loader import load_world
    world, notes = compose_to_world(open(a.file).read(), a.graph)
    drop_graph(a.graph)
    load_world(get_graph(a.graph), world)
    print(f"loaded {len(world['services'])} services, {len(world['deps'])} edges into graph {a.graph!r}")
    for n in notes:
        print(" note:", n)


if __name__ == "__main__":
    main()
