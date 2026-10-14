"""Record a replay for the "daily cap reached" fallback. Uses a dev scenario (never the held-out test set)."""
import json

from backend.app.main import REPLAY_FILE
from backend.agents.runner import run_investigation
from backend.graph.db import drop_graph, get_graph
from backend.world import failure
from backend.world.loader import load_world
from backend.world.scenarios import load_specs, materialize

if __name__ == "__main__":
    spec = next(s for s in load_specs("dev") if s["id"] == "dev-hard-2")
    world, o = materialize(spec)
    now = 1_800_000_000
    drop_graph("replay_tmp")
    g = get_graph("replay_tmp")
    load_world(g, world, now=now)
    failure.apply_outcome(g, o, now)
    events = []
    run_investigation(g, o.alerting, now=now, emit=events.append)
    REPLAY_FILE.write_text(json.dumps(events, indent=1, default=str))
    drop_graph("replay_tmp")
    print(len(events), "events")
