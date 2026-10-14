"""End-to-end investigation with the rule policy (no API key). Uses DEV scenarios only."""
import json

import pytest

from backend.agents.runner import run_investigation
from backend.graph.db import drop_graph, get_graph
from backend.tests.conftest import NOW
from backend.world import failure
from backend.world.loader import load_world
from backend.world.scenarios import load_specs, materialize

DEV = {s["id"]: s for s in load_specs("dev")}


def run(spec_id):
    world, o = materialize(DEV[spec_id])
    name = "t_run_" + spec_id.replace("-", "_")
    drop_graph(name)
    g = get_graph(name)
    load_world(g, world, now=NOW)
    failure.apply_outcome(g, o, NOW)
    events = []
    res = run_investigation(g, o.alerting, now=NOW, emit=events.append)
    return g, o, res, events, name


@pytest.mark.parametrize("sid", [k for k in DEV if "ambiguous" not in k])
def test_dev_scenarios_find_the_true_cause(sid):
    g, o, res, events, name = run(sid)
    try:
        assert res["root_cause"] == DEV[sid]["roots"][0]
        assert res["confidence"] in ("high", "medium")
        assert res["claims"]["rejected"] == 0 and res["claims"]["verified"] >= 8
        assert res["blames_deploy"] == o.truth["deploy_ids"][0]
    finally:
        drop_graph(name)


def test_two_cause_storm_abstains():
    g, o, res, events, name = run("dev-ambiguous-1")
    try:
        assert res["root_cause"] == "undetermined" and res["confidence"] == "low"
        assert "more than one cause" in " ".join(res["reasons"]).lower()
        assert res["actions"] == [] and "UNDETERMINED" in res["message"]
    finally:
        drop_graph(name)


def test_everything_is_in_the_graph_and_events_stream():
    g, o, res, events, name = run("dev-medium-1")
    try:
        types = [e["type"] for e in events]
        assert types[0] == "start" and types[-1] == "done" and "hypotheses" in types and "decision" in types and "verify" in types
        assert {e["agent"] for e in events} >= {"Lead", "Impact", "Changes", "History", "People"}
        board = g.query("MATCH (:Investigation)-[:CONSIDERS]->(h:Hypothesis)<-[:SUPPORTS|WEAKENS]-(f:Finding)<-[:WROTE]-(a:Agent) RETURN count(DISTINCT a.name)").result_set[0][0]
        assert board == 4                                    # all four specialists wrote to the graph
        assert g.query("MATCH (:Investigation)-[:CONCLUDED]->(d:Decision)-[:BLAMES]->(:Deploy) RETURN count(d)").result_set[0][0] == 1
        # every finding cites at least one node and carries a receipt
        assert g.query("MATCH (f:Finding) WHERE NOT (f)-[:CITES]->() RETURN count(f)").result_set[0][0] == 0
        assert g.query("MATCH (f:Finding) WHERE f.receipt IS NULL RETURN count(f)").result_set[0][0] == 0
        assert json.loads(g.query("MATCH (d:Decision) RETURN d.actions").result_set[0][0])[0]["action"] in ("rollback", "restart", "scale", "hotfix", "config")
        assert "needs human approval" in res["message"]
    finally:
        drop_graph(name)


def test_parallel_runs_do_not_collide_on_finding_ids():
    for _ in range(3):
        g, o, res, events, name = run("dev-hard-2")
        try:
            ids = [r[0] for r in g.query("MATCH (f:Finding) RETURN f.id").result_set]
            assert len(ids) == len(set(ids))
        finally:
            drop_graph(name)


def test_investigation_is_fast():
    g, o, res, events, name = run("dev-hard-1")
    drop_graph(name)
    assert res["duration_s"] < 5          # design target is < 60 s with the LLM in the loop
