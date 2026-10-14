import random

import pytest

from backend.graph.db import copy_graph, drop_graph, get_graph
from backend.tests.conftest import NOW
from backend.tools.registry import TOOLS, call_tool, tool_specs
from backend.world import failure, get_world, topology as topo


def test_registry_has_all_read_tools_and_schemas():
    assert {"rank_root_causes", "blast_radius", "dependencies", "recent_changes", "change_details", "find_experts",
            "similar_incidents", "lessons_for", "critical_services", "path_between", "explore_graph"} <= set(TOOLS)
    for spec in tool_specs():
        assert spec["input_schema"]["type"] == "object" and spec["description"]


def test_call_tool_validates_arguments(acme_graph):
    with pytest.raises(ValueError, match="missing"):
        call_tool(acme_graph, "blast_radius", {})
    with pytest.raises(ValueError, match="unexpected"):
        call_tool(acme_graph, "blast_radius", {"service": "kafka", "evil": 1})
    with pytest.raises(KeyError):
        call_tool(acme_graph, "drop_everything", {})


def test_blast_radius_matches_independent_python_computation(acme_graph):
    w = get_world("acme")
    for svc in ("ledger-db", "auth-svc", "kafka"):
        r = call_tool(acme_graph, "blast_radius", {"service": svc}).data
        affected = {svc} | set(topo.sync_dependents(w, svc))
        assert {f["service"] for f in r["failing_now"]} == set(topo.sync_dependents(w, svc))
        feats = set(topo.features_hit(w, affected))
        assert set(r["features"]) == feats
        custs = [c for c in w["customers"] if set(c["features"]) & feats]
        assert r["arr_at_risk"] == sum(c["arr"] for c in custs)          # each customer counted once
        assert len(r["customers"]) == len(custs)


def test_blast_radius_async_at_risk(acme_graph):
    r = call_tool(acme_graph, "blast_radius", {"service": "kafka"}).data
    assert set(r["at_risk_async"]) >= {"notif-worker", "reporting-svc", "audit-svc"}
    assert {f["service"] for f in r["failing_now"]} == {"notifications-api", "mobile-bff"}


def test_dependencies(acme_graph):
    r = call_tool(acme_graph, "dependencies", {"service": "payments-api", "kind": "sync"}).data
    assert {d["service"] for d in r["direct"]} == {"ledger-svc", "fraud-svc", "pricing-svc", "auth-svc", "redis-cache"}
    names = {d["service"]: d["hops"] for d in r["all"]}
    assert names["ledger-db"] == 2 and names["fraud-store"] == 2
    assert all(d["hops"] <= 6 for d in r["all"])


def test_path_between(acme_graph):
    r = call_tool(acme_graph, "path_between", {"a": "web-gateway", "b": "ledger-db"}).data
    assert r["connected"] and r["path"][0] == "web-gateway" and r["path"][-1] == "ledger-db" and r["hops"] == 3
    r = call_tool(acme_graph, "path_between", {"a": "ledger-db", "b": "web-gateway"}).data   # reverse direction also found
    assert r["connected"] and r["path"][0] == "web-gateway"
    assert not call_tool(acme_graph, "path_between", {"a": "search-api", "b": "ledger-db"}).data["connected"]


def test_critical_services_finds_chokepoints(acme_graph):
    top = [c["service"] for c in call_tool(acme_graph, "critical_services", {"limit": 5}).data["critical"]]
    assert "auth-svc" in top and "payments-api" in top


def test_find_experts_is_timezone_aware(acme_graph):
    from datetime import datetime, timezone
    # NOW is 07:30 UTC => IST 13:00 (awake), CET 08:30/09:30 (awake), PST night (asleep)
    r = call_tool(acme_graph, "find_experts", {"service": "ledger-db", "at_time": NOW}).data
    by_tz = {}
    for p in r["experts"]:
        by_tz.setdefault(p["timezone"], set()).add(p["awake"])
        local = datetime.fromtimestamp(NOW, tz=timezone.utc).hour
    assert by_tz.get("Asia/Kolkata", {True}) == {True}
    assert r["owner_team"] == "Ledger"
    asleep = call_tool(acme_graph, "find_experts", {"service": "auth-svc", "at_time": NOW}).data["experts"]
    assert any(not p["awake"] for p in asleep if p["timezone"] == "America/Los_Angeles")
    oncall = [p for p in r["experts"] if "on-call" in p["roles"]]
    assert oncall and oncall[0]["team"] == "Ledger"


def test_similar_incidents_finds_planted_patterns(acme_graph):
    r = call_tool(acme_graph, "similar_incidents", {"service": "ledger-db", "text": "connection pool exhausted after config change"}).data
    top = r["incidents"][0]
    assert top["root_cause_service"] == "ledger-db" and top["action"] == "rollback"
    assert "same root-cause service" in top["why"]
    k = call_tool(acme_graph, "similar_incidents", {"service": "kafka"}).data["incidents"]
    assert k and all(i["root_cause_service"] == "kafka" for i in k[:3]) and k[0]["action"] == "scale"


def test_similar_incidents_text_only_match(acme_graph):
    r = call_tool(acme_graph, "similar_incidents", {"service": "search-api", "text": "certificate rotation"}).data["incidents"]
    assert any("certificate" in i["title"] for i in r)


def test_lessons_for(acme_graph):
    r = call_tool(acme_graph, "lessons_for", {"service": "payments-api"}).data["lessons"]
    pats = {l["about"]: l for l in r}
    assert pats["ledger-db"]["hops"] == 2 and pats["ledger-db"]["times_seen"] >= 3
    assert pats["auth-svc"]["hops"] == 1
    assert call_tool(acme_graph, "lessons_for", {"service": "search-index"}).data["lessons"] == []


def test_recent_changes_finds_trigger_and_distractors(fresh_graph):
    w = get_world("acme")
    o = failure.break_service(w, "ledger-db", "config", dict(flaky=True, missing=True, distractors=2), random.Random(11))
    failure.apply_outcome(fresh_graph, o, NOW)
    until = NOW - o.first_alert_age_s
    r = call_tool(fresh_graph, "recent_changes", {"services": ["ledger-db"], "until_ts": until, "window_minutes": 120}).data
    ids = {c["deploy_id"] for c in r["changes"]}
    assert o.truth["deploy_ids"][0] in ids
    trig = next(c for c in r["changes"] if c["deploy_id"] == o.truth["deploy_ids"][0])
    assert 20 <= trig["minutes_before"] <= 60 and trig["service"] == "ledger-db"
    d = call_tool(fresh_graph, "change_details", {"deploy_id": trig["deploy_id"]}).data
    assert d["author"]["team"] == "Ledger" and d["commits"]


def test_explore_graph_is_read_only(acme_graph):
    r = call_tool(acme_graph, "explore_graph", {"cypher": "MATCH (s:Service) RETURN s.name ORDER BY s.name", "limit": 3}).data
    assert len(r["rows"]) == 3 and r["truncated"]
    with pytest.raises(Exception):
        call_tool(acme_graph, "explore_graph", {"cypher": "CREATE (:Hacked)"})
    assert acme_graph.query("MATCH (n:Hacked) RETURN count(n)").result_set[0][0] == 0


def test_injection_attempt_in_service_name_is_inert(acme_graph):
    with pytest.raises(ValueError, match="unknown service"):
        call_tool(acme_graph, "blast_radius", {"service": "x'}) DETACH DELETE s //"})
    assert acme_graph.query("MATCH (s:Service) RETURN count(s)").result_set[0][0] == 30


def test_tool_results_carry_cites_and_receipts(acme_graph):
    r = call_tool(acme_graph, "blast_radius", {"service": "ledger-db"})
    assert "Service:ledger-db" in r.cites and r.receipt["tool"] == "blast_radius"


def test_graph_copy_is_independent(fresh_graph):
    name = "t_copy_x"
    cp = copy_graph(fresh_graph.name, name)
    cp.query("MATCH (s:Service {name:'kafka'}) SET s.monitored = true")
    orig = fresh_graph.query("MATCH (s:Service {name:'kafka'}) RETURN s.monitored").result_set[0][0]
    assert orig is False
    drop_graph(name)
