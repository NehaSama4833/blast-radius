"""Ripple: a late alert re-does only the findings it can change. DEV scenarios only."""
import pytest

from backend.agents.ripple import ripple
from backend.agents.runner import run_investigation
from backend.graph.db import drop_graph, get_graph
from backend.tests.conftest import NOW
from backend.world import failure
from backend.world.loader import load_world
from backend.world.scenarios import load_specs, materialize

DEV = {s["id"]: s for s in load_specs("dev")}


def setup(sid):
    world, o = materialize(DEV[sid])
    name = "t_rip_" + sid.replace("-", "_")
    drop_graph(name)
    g = get_graph(name)
    load_world(g, world, now=NOW)
    failure.apply_outcome(g, o, NOW)
    return g, o, name


@pytest.mark.parametrize("sid", ["dev-hard-2", "dev-medium-1"])
def test_late_alerts_redo_only_what_they_change(sid):
    g, o, name = setup(sid)
    try:
        full = o.alerting
        late = full[-2:]
        first = [a for a in full if a not in late]
        res0 = run_investigation(g, first, now=NOW)
        n_findings = g.query("MATCH (f:Finding) RETURN count(f)").result_set[0][0]
        events = []
        res1 = ripple(g, res0, late, now=NOW, emit=events.append)
        r = res1["ripple"]
        assert set(r["new_alerts"]) == set(late) and r["kept"] > 0          # something was kept without re-running
        assert sorted(res1["alerting"]) == sorted(full)
        # the audit trail survives: nothing was deleted, old findings are only retired
        assert g.query("MATCH (f:Finding) RETURN count(f)").result_set[0][0] >= n_findings
        assert g.query("MATCH (:Investigation {id:$i})-[:CONCLUDED]->(d:Decision) RETURN count(d)", {"i": res0["investigation"]}).result_set[0][0] == 1
        assert g.query("MATCH (:Investigation {id:$i})-[:PREVIOUSLY_CONCLUDED]->(d:Decision) RETURN count(d)", {"i": res0["investigation"]}).result_set[0][0] == 1
        assert res1["claims"]["rejected"] == 0
        assert all(e.get("ripple") for e in events)
        # with the full alert set the answer matches a from-scratch investigation of the same storm
        fresh = run_investigation(g, full, now=NOW)
        assert res1["root_cause"] == fresh["root_cause"]
    finally:
        drop_graph(name)


def test_late_alert_on_a_service_already_counted_is_a_noop():
    g, o, name = setup("dev-hard-2")
    try:
        res0 = run_investigation(g, o.alerting, now=NOW)
        res1 = ripple(g, res0, [o.alerting[0]], now=NOW)
        assert res1["ripple"]["new_alerts"] == [] and res1["root_cause"] == res0["root_cause"]
    finally:
        drop_graph(name)
