import random

import pytest

from backend.graph import sandbox
from backend.graph.db import drop_graph, get_graph
from backend.tests.conftest import NOW
from backend.tools.registry import call_tool
from backend.tools.verify import verify_mitigation, world_from_graph
from backend.world import failure, get_world


def test_alerting_for_matches_break_service_without_noise():
    w = get_world("acme")
    for root in ("ledger-db", "kafka", "payments-api", "redis-cache"):
        o = failure.break_service(w, root, "config", rng=random.Random(1))
        assert set(failure.alerting_for(w, [root])) == set(o.alerting)
        assert {s for s, sig in failure.alerting_for(w, [root]).items() if sig == "lag"} == set(o.lag_alerting)


def test_world_from_graph_matches_world(acme_graph):
    g = world_from_graph(acme_graph)
    w = get_world("acme")
    assert len(g["services"]) == 30 and len(g["deps"]) == len(w["deps"])


def test_rollback_of_true_cause_clears_everything(fresh_graph):
    o = failure.break_service(get_world("acme"), "ledger-db", "config", rng=random.Random(5))
    failure.apply_outcome(fresh_graph, o, NOW)
    r = verify_mitigation(fresh_graph, "rollback", "ledger-db", o.alerting, deploy_id=o.truth["deploy_ids"][0])
    assert r.data["all_clear"] and r.data["simulated"] and len(r.data["cleared"]) == len(o.alerting)
    assert "clears 11 of 11 alerts" in r.data["summary"] and "Simulation" in r.data["summary"]
    # the original graph is untouched and the scratch copy is gone
    assert fresh_graph.query("MATCH (d:Deploy {rolled_back:true}) RETURN count(d)").result_set[0][0] == 0
    assert fresh_graph.query("MATCH (s:Service {healthy:true}) RETURN count(s)").result_set[0][0] == 0


def test_fixing_the_wrong_service_leaves_alerts(fresh_graph):
    o = failure.break_service(get_world("acme"), "ledger-db", "config", rng=random.Random(5))
    failure.apply_outcome(fresh_graph, o, NOW)
    r = verify_mitigation(fresh_graph, "restart", "fraud-svc", o.alerting)
    assert not r.data["all_clear"] and r.data["remaining"]


def test_async_lag_drain_time_is_reported(fresh_graph):
    o = failure.break_service(get_world("acme"), "kafka", "infra", rng=random.Random(2))
    failure.apply_outcome(fresh_graph, o, NOW)
    r = verify_mitigation(fresh_graph, "scale", "kafka", o.alerting)
    assert r.data["all_clear"] and r.data["drain_minutes"] == 10 and "ledger-svc" in r.data["lag_draining"]


def test_second_cause_is_reported_as_remaining(fresh_graph):
    a = failure.break_service(get_world("acme"), "ledger-db", "config", rng=random.Random(5))
    b = failure.break_service(get_world("acme"), "fraud-store", "config", rng=random.Random(6), _id_offset=4)
    m = failure.merge(get_world("acme"), [a, b])
    failure.apply_outcome(fresh_graph, m, NOW)
    r = verify_mitigation(fresh_graph, "rollback", "ledger-db", m.alerting, deploy_id=a.truth["deploy_ids"][0])
    assert not r.data["all_clear"] and "risk-engine" in r.data["remaining"]


def test_verify_validates_inputs(fresh_graph):
    with pytest.raises(ValueError, match="deploy_id"):
        verify_mitigation(fresh_graph, "rollback", "ledger-db", ["payments-api"])
    with pytest.raises(ValueError, match="not a deploy"):
        verify_mitigation(fresh_graph, "rollback", "ledger-db", ["payments-api"], deploy_id="d-1")
    with pytest.raises(ValueError, match="unknown action"):
        verify_mitigation(fresh_graph, "explode", "ledger-db", ["payments-api"])


def test_sandbox_is_isolated_and_time_shifted():
    tmpl = "t_tmpl_sbx"
    drop_graph(tmpl)
    from backend.world.loader import load_world
    load_world(get_graph(tmpl), get_world("acme"), now=NOW)
    later = NOW + 5 * 86400                       # template is 5 days old when the visitor arrives
    name = sandbox.create_sandbox(tmpl, now=later)
    try:
        g = get_graph(name)
        newest_t = get_graph(tmpl).query("MATCH (d:Deploy) RETURN max(d.ts)").result_set[0][0]
        newest_s = g.query("MATCH (d:Deploy) RETURN max(d.ts)").result_set[0][0]
        assert newest_s - newest_t == 5 * 86400           # times moved so "now" is true again
        g.query("MATCH (s:Service {name:'kafka'}) SET s.monitored = true")
        assert get_graph(tmpl).query("MATCH (s:Service {name:'kafka'}) RETURN s.monitored").result_set[0][0] is False
        assert name in sandbox.list_sandboxes()
        assert name not in sandbox.cleanup_expired(now=later + 60)          # still fresh (other, older sandboxes may be swept)
        assert name in sandbox.cleanup_expired(now=later + sandbox.TTL_S + 1)
        assert name not in sandbox.list_sandboxes()
    finally:
        drop_graph(name)
        drop_graph(tmpl)


def test_sandbox_cap(monkeypatch):
    tmpl = "t_tmpl_cap"
    drop_graph(tmpl)
    from backend.world.loader import load_world
    load_world(get_graph(tmpl), get_world("globex"), now=NOW)
    monkeypatch.setattr(sandbox, "MAX_SANDBOXES", 2)
    made = [sandbox.create_sandbox(tmpl, now=NOW) for _ in range(2)]
    try:
        with pytest.raises(sandbox.SandboxLimit):
            sandbox.create_sandbox(tmpl, now=NOW)
    finally:
        for n in made:
            drop_graph(n)
        drop_graph(tmpl)
