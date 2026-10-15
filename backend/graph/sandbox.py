"""Per-visitor sandbox graphs: GRAPH.COPY of a template, timestamps shifted to "now", TTL 2h, capped count.

State lives in the database itself (a Meta node inside each sandbox), so it survives restarts and needs no registry.
"""
import secrets
import time

from backend.graph.db import copy_graph, drop_graph, get_db

PREFIX = "sbx_"
TTL_S = 2 * 3600
MAX_SANDBOXES = 50


class SandboxLimit(RuntimeError):
    pass


def list_sandboxes():
    return sorted(n for n in get_db().list_graphs() if n.startswith(PREFIX))


def _shift_times(g, delta):
    """Move every timestamp by `delta` seconds so the copy looks like it was seeded just now."""
    for label, props in (("Deploy", ["ts"]), ("Commit", ["ts"]), ("Alert", ["ts"]),
                         ("Incident", ["started_at", "resolved_at"]), ("Lesson", ["last_seen"])):
        sets = ", ".join(f"n.{p} = n.{p} + $d" for p in props)
        g.query(f"MATCH (n:{label}) SET {sets}", {"d": int(delta)})


def create_sandbox(template: str, now=None):
    now = int(now if now is not None else time.time())
    cleanup_expired(now)
    if len(list_sandboxes()) >= MAX_SANDBOXES:
        raise SandboxLimit("sandbox limit reached, try again later")
    name = PREFIX + secrets.token_hex(4)
    g = copy_graph(template, name)
    loaded = g.query("MATCH (m:Meta) RETURN m.loaded_at").result_set
    delta = now - loaded[0][0] if loaded else 0
    if delta:
        _shift_times(g, delta)
    g.query("MATCH (m:Meta) DELETE m")
    g.query("CREATE (:Meta {loaded_at: $now, world: $t, created_at: $now, sandbox: true})", {"now": now, "t": template})
    return name


def cleanup_expired(now=None, ttl=TTL_S):
    now = int(now if now is not None else time.time())
    dropped = []
    for n in list_sandboxes():
        from backend.graph.db import get_graph
        r = get_graph(n).query("MATCH (m:Meta) RETURN m.created_at").result_set
        if not r or now - r[0][0] > ttl:
            drop_graph(n)
            dropped.append(n)
    return dropped


def create_from_world(world, now=None):
    """A sandbox built from a world dict instead of a template (used for "bring your own docker-compose")."""
    import json
    from backend.graph.db import get_graph
    from backend.world.loader import load_world
    now = int(now if now is not None else time.time())
    cleanup_expired(now)
    if len(list_sandboxes()) >= MAX_SANDBOXES:
        raise SandboxLimit("sandbox limit reached, try again later")
    name = PREFIX + secrets.token_hex(4)
    g = get_graph(name)
    load_world(g, world, now=now)
    g.query("MATCH (m:Meta) SET m.created_at = $now, m.sandbox = true, m.world_json = $w", {"now": now, "w": json.dumps(world)})
    return name
