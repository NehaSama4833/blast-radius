import json
import subprocess
import sys

from backend.world import get_world, topology as topo
from backend.world.history import world_digest


def test_sizes():
    a, g = get_world("acme"), get_world("globex")
    assert len(a["services"]) == 30 and len(g["services"]) == 15
    assert 20 <= len(a["incidents"]) <= 30
    assert len(a["people"]) == 18


def test_world_is_deterministic_across_processes():
    code = "from backend.world import get_world;from backend.world.history import world_digest;print(world_digest(get_world('acme')),world_digest(get_world('globex')))"
    outs = {subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True,
                           env={"PYTHONHASHSEED": str(s), "PYTHONPATH": "."}).stdout for s in (1, 2)}
    assert len(outs) == 1
    assert outs.pop().split() == [world_digest(get_world("acme")), world_digest(get_world("globex"))]


def test_dags_and_silent_stores():
    for name in ("acme", "globex"):
        w = get_world(name)
        assert topo.is_dag(w)
        silent = [s["name"] for s in w["services"] if not s["monitored"]]
        assert len(silent) >= 3
    assert "ledger-db" in [s["name"] for s in get_world("acme")["services"] if not s["monitored"]]


def test_timezones_cover_ist_cet_pst():
    tz = {p["timezone"] for p in get_world("acme")["people"]}
    assert tz == {"Asia/Kolkata", "Europe/Berlin", "America/Los_Angeles"}


def test_planted_patterns_present():
    w = get_world("acme")
    by = {}
    for i in w["incidents"]:
        by.setdefault((i["root"], i["title"]), []).append(i)
    assert len(by[("ledger-db", "ledger-db connection pool exhausted")]) >= 3
    assert len(by[("kafka", "kafka partition rebalance consumer lag")]) >= 3
    assert len(by[("auth-svc", "auth-svc certificate rotation failures")]) >= 3
    assert {l["service"] for l in w["lessons"]} == {"ledger-db", "kafka", "auth-svc"}


def test_no_background_deploys_in_last_3h():
    recent = [d for d in get_world("acme")["deploys"] if d["age_s"] < 3 * 3600]
    assert recent == []


def test_loader_makes_relative_timestamps(acme_graph):
    from backend.tests.conftest import NOW

    r = acme_graph.query("MATCH (d:Deploy) RETURN max(d.ts)").result_set[0][0]
    assert NOW - r >= 3 * 3600
    assert acme_graph.query("MATCH (n:Service) RETURN count(n)").result_set[0][0] == 30


def test_fulltext_index_on_incident_summary(acme_graph):
    rows = acme_graph.query("CALL db.idx.fulltext.queryNodes('Incident','certificate') YIELD node RETURN node.id").result_set
    assert len(rows) >= 3
