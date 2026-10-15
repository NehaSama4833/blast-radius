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

import yaml

DATA = ("postgres", "mysql", "mariadb", "mongo", "redis", "memcached", "elasticsearch", "cassandra", "clickhouse")
BROKER = ("kafka", "rabbitmq", "nats", "redpanda", "pulsar")


def _image(svc):
    return str(svc.get("image", "")).lower()


def _depends(svc):
    d = svc.get("depends_on") or []
    return list(d) if isinstance(d, (list, dict)) else []


def compose_to_world(text, name="imported"):
    doc = yaml.safe_load(text) or {}
    svcs = doc.get("services")
    if not isinstance(svcs, dict) or not svcs:
        raise ValueError("no services found in the compose file")
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
            if d not in svcs:
                notes.append(f"{n}: depends_on {d!r} is not a service in this file, skipped")
                continue
            deps.append(dict(src=n, dst=d, kind="async" if d in brokers else "sync"))
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
