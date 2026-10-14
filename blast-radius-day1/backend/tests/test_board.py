import json
import random

import pytest

from backend.agents.board import BoardError, CitationError, start_investigation
from backend.agents.memory import record_resolution
from backend.tests.conftest import NOW
from backend.tools.registry import call_tool
from backend.world import failure, get_world


def storm(graph, root="ledger-db", seed=5, noise=None):
    o = failure.break_service(get_world("acme"), root, "config", noise, random.Random(seed))
    failure.apply_outcome(graph, o, NOW)
    return o


def test_agents_coordinate_only_through_the_graph(fresh_graph):
    o = storm(fresh_graph)
    s = start_investigation(fresh_graph, o.alerting, now=NOW)
    r = s.call("Lead", "rank_root_causes", {"alerting": o.alerting})
    hyps = s.create_hypotheses(r.data["candidates"][:3])
    # Changes agent finds the deploy and writes a finding
    ch = s.call("Changes", "recent_changes", {"services": ["ledger-db"], "until_ts": NOW - o.first_alert_age_s})
    dep = o.truth["deploy_ids"][0]
    s.add_finding("Changes", hyps[0], f"config deploy {dep} shipped before the first alert", True, [f"Deploy:{dep}", "Service:ledger-db"])
    # History agent
    s.call("History", "similar_incidents", {"service": "ledger-db", "text": "connection pool exhausted"})
    inc = s.call("History", "similar_incidents", {"service": "ledger-db"}).data["incidents"][0]["incident_id"]
    s.add_finding("History", hyps[0], "same pattern as a past incident", True, [f"Incident:{inc}"])
    # The Lead's view is a graph query: it sees both findings, tagged with the agents that wrote them
    board = s.read_board()
    assert [h["service"] for h in board][0] == "ledger-db"
    assert {f["agent"] for f in board[0]["findings"]} == {"Changes", "History"}
    assert {f["kind"] for f in board[0]["findings"]} == {"temporal", "historical"}
    assert fresh_graph.query("MATCH (:Finding)-[:CITES]->(d:Deploy {id:$d}) RETURN count(*)", {"d": dep}).result_set[0][0] == 1
    assert s.verification() == dict(verified=2, rejected=0)


def test_citation_check_rejects_nodes_the_agent_never_saw(fresh_graph):
    o = storm(fresh_graph)
    s = start_investigation(fresh_graph, o.alerting, now=NOW)
    hyps = s.create_hypotheses(s.call("Lead", "rank_root_causes", {"alerting": o.alerting}).data["candidates"][:2])
    with pytest.raises(CitationError) as e:
        s.add_finding("Changes", hyps[0], "made-up deploy", True, ["Deploy:d-99999"])
    assert "Deploy:d-99999" in e.value.bad
    # an id some OTHER agent saw is still not allowed for this agent
    s.call("Impact", "blast_radius", {"service": "ledger-db"})
    with pytest.raises(CitationError):
        s.add_finding("Changes", hyps[0], "borrowed evidence", True, ["Feature:Checkout"])
    with pytest.raises(BoardError, match="at least one"):
        s.add_finding("Changes", hyps[0], "no evidence", True, [])
    assert s.verification()["rejected"] == 3
    assert fresh_graph.query("MATCH (f:Finding) RETURN count(f)").result_set[0][0] == 0


def test_agents_are_scoped_by_the_server(fresh_graph):
    o = storm(fresh_graph)
    s = start_investigation(fresh_graph, o.alerting, now=NOW)
    with pytest.raises(BoardError, match="may not call"):
        s.call("People", "recent_changes", {"services": ["ledger-db"], "until_ts": NOW})
    with pytest.raises(BoardError, match="may not call"):
        s.call("History", "explore_graph", {"cypher": "MATCH (n) RETURN n"})
    with pytest.raises(BoardError, match="unknown agent"):
        s.call("Mallory", "blast_radius", {"service": "kafka"})
    with pytest.raises(BoardError, match="only the Lead"):
        s.propose_action("Impact", "rollback", "ledger-db", "d-1", "x", [])
    with pytest.raises(BoardError, match="not a hypothesis"):
        s.call("People", "find_experts", {"service": "ledger-db", "at_time": NOW})
        s.add_finding("People", "h-other-1", "x", True, ["Service:ledger-db"])


def test_receipts_record_tool_params_and_graph_version(fresh_graph):
    o = storm(fresh_graph)
    s = start_investigation(fresh_graph, o.alerting, now=NOW)
    hyps = s.create_hypotheses(s.call("Lead", "rank_root_causes", {"alerting": o.alerting}).data["candidates"][:1])
    s.call("Impact", "blast_radius", {"service": "ledger-db"})
    fid = s.add_finding("Impact", hyps[0], "checkout is hit", True, ["Feature:Checkout"])
    rec = json.loads(fresh_graph.query("MATCH (f:Finding {id:$f}) RETURN f.receipt", {"f": fid}).result_set[0][0])
    assert rec["graph_version"] == f"acme@{NOW}"
    assert rec["calls"] == [dict(tool="blast_radius", params=dict(service="ledger-db"))]
    assert rec["nodes_read"] == ["Feature:Checkout"]


def test_decision_and_abstention(fresh_graph):
    o = storm(fresh_graph)
    s = start_investigation(fresh_graph, o.alerting, now=NOW)
    r = s.call("Lead", "rank_root_causes", {"alerting": o.alerting})
    s.create_hypotheses(r.data["candidates"][:2])
    with pytest.raises(BoardError, match="abstention"):
        s.record_decision(None, "high", ["unsure"], ["Service:ledger-db"])
    with pytest.raises(BoardError, match="reasons"):
        s.record_decision("ledger-db", "high", [], ["Service:ledger-db"])
    with pytest.raises(CitationError):
        s.record_decision("ledger-db", "high", ["trust me"], ["Service:not-seen"])
    d = s.record_decision("ledger-db", "high", ["explains 11 of 11 alerts"], ["Service:ledger-db"], blames_deploy=None)
    assert d["root_cause"] == "ledger-db"
    st = {h["service"]: h["status"] for h in s.read_board()}
    assert st["ledger-db"] == "accepted" and all(v == "rejected" for k, v in st.items() if k != "ledger-db")


def test_abstain_is_recorded_as_undetermined(fresh_graph):
    o = storm(fresh_graph)
    s = start_investigation(fresh_graph, o.alerting, now=NOW)
    s.call("Lead", "rank_root_causes", {"alerting": o.alerting})
    s.record_decision(None, "low", ["more than one possible cause"], ["Service:ledger-db"])
    assert fresh_graph.query("MATCH (d:Decision) RETURN d.root_cause, d.confidence").result_set == [["undetermined", "low"]]


def test_resolution_creates_lesson_and_next_storm_uses_it(fresh_graph):
    """Memory that changes behaviour: after 'Mark resolved', lessons_for / similar_incidents return the new knowledge."""
    o = storm(fresh_graph, root="redis-cache", seed=7)
    dep = o.truth["deploy_ids"][0]
    assert call_tool(fresh_graph, "lessons_for", {"service": "redis-cache"}).data["lessons"] == []
    s = start_investigation(fresh_graph, o.alerting, now=NOW)
    s.create_hypotheses(s.call("Lead", "rank_root_causes", {"alerting": o.alerting}).data["candidates"][:1])
    s.call("Changes", "recent_changes", {"services": ["redis-cache"], "until_ts": NOW - o.first_alert_age_s})
    s.record_decision("redis-cache", "medium", ["explains most alerts"], ["Service:redis-cache"], blames_deploy=None)
    # blame the deploy so the Incident links to it
    fresh_graph.query("MATCH (:Investigation {id:$i})-[:CONCLUDED]->(d:Decision), (x:Deploy {id:$x}) CREATE (d)-[:BLAMES]->(x)", {"i": s.inv_id, "x": dep})
    res = record_resolution(fresh_graph, s.inv_id, "rollback", "Rolled back the redis-cache change", 6, now=NOW + 600, responders=["emma"])
    assert res["incident_id"].startswith("INC-")
    lessons = call_tool(fresh_graph, "lessons_for", {"service": "redis-cache"}).data["lessons"]
    assert len(lessons) == 1 and lessons[0]["times_seen"] == 1 and lessons[0]["avg_ttr_min"] == 6.0
    inc = call_tool(fresh_graph, "similar_incidents", {"service": "redis-cache"}).data["incidents"]
    assert inc[0]["incident_id"] == res["incident_id"] and inc[0]["action"] == "rollback"
    # a second resolution of the same kind updates the same lesson instead of duplicating it
    s2 = start_investigation(fresh_graph, o.alerting, now=NOW + 700)
    s2.call("Lead", "rank_root_causes", {"alerting": o.alerting})
    s2.record_decision("redis-cache", "high", ["same as last time"], ["Service:redis-cache"])
    fresh_graph.query("MATCH (:Investigation {id:$i})-[:CONCLUDED]->(d:Decision), (x:Deploy {id:$x}) CREATE (d)-[:BLAMES]->(x)", {"i": s2.inv_id, "x": dep})
    record_resolution(fresh_graph, s2.inv_id, "rollback", "Rolled back again", 4, now=NOW + 900)
    lessons = call_tool(fresh_graph, "lessons_for", {"service": "redis-cache"}).data["lessons"]
    assert len(lessons) == 1 and lessons[0]["times_seen"] == 2 and lessons[0]["avg_ttr_min"] == 5.0


def test_cannot_resolve_undetermined(fresh_graph):
    o = storm(fresh_graph)
    s = start_investigation(fresh_graph, o.alerting, now=NOW)
    s.call("Lead", "rank_root_causes", {"alerting": o.alerting})
    s.record_decision(None, "low", ["unsure"], ["Service:ledger-db"])
    with pytest.raises(ValueError, match="undetermined"):
        record_resolution(fresh_graph, s.inv_id, "rollback", "x", 5, now=NOW)
