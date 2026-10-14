"""Golden tests for rank_root_causes. Only DEV scenarios are used here; the held-out test split is never touched by the test suite."""
import pytest

from backend.graph.db import drop_graph, get_graph
from backend.tests.conftest import NOW
from backend.tools.ranking import f1, score_candidates
from backend.tools.registry import call_tool
from backend.world import failure, get_world
from backend.world.loader import load_world
from backend.world.scenarios import load_specs, materialize
import random


def test_f1_basic():
    assert f1(1, 1) == 1
    assert f1(0, 0) == 0
    assert round(f1(1, 0.5), 4) == 0.6667


def test_score_candidates_golden_numbers():
    meta = {"x": dict(monitored=True, layer="core"), "y": dict(monitored=False, layer="data")}
    alerting = {"a", "b", "c", "d"}
    explains = {"x": {"a", "b", "c", "d"}, "y": {"a", "b", "c"}}
    predicts = {"x": set("abcdefgh"), "y": {"a", "b", "c", "e"}}   # x: 4/8 precision, y: 3/4
    r = score_candidates(alerting, explains, predicts, meta)
    by = {c["candidate"]: c for c in r}
    assert (by["x"]["coverage"], by["x"]["precision"], by["x"]["score"]) == (1.0, 0.5, 0.6667)
    assert (by["y"]["coverage"], by["y"]["precision"], by["y"]["score"]) == (0.75, 0.75, 0.75)
    assert r[0]["candidate"] == "y"
    assert by["y"]["unexplained"] == ["d"] and by["y"]["predicted_not_alerting"] == ["e"]


def test_tie_goes_to_silent_then_deeper():
    meta = {"api": dict(monitored=True, layer="api"), "db": dict(monitored=False, layer="data"),
            "svc": dict(monitored=True, layer="core")}
    ex = {k: {"a"} for k in meta}
    pr = {k: {"a"} for k in meta}
    assert [c["candidate"] for c in score_candidates({"a"}, ex, pr, meta)] == ["db", "svc", "api"]


def test_shared_dependency_does_not_beat_the_true_silent_cause(acme_graph):
    w = get_world("acme")
    o = failure.break_service(w, "ledger-db", "config", rng=random.Random(5))
    r = call_tool(acme_graph, "rank_root_causes", {"alerting": o.alerting}).data
    top = r["candidates"][0]
    assert top["candidate"] == "ledger-db" and top["coverage"] == 1.0
    assert not r["likely_multiple_causes"]
    # auth-svc is reachable from many alerting services but would break healthy ones, so it must rank lower
    others = {c["candidate"]: c for c in r["candidates"]}
    if "auth-svc" in others:
        assert others["auth-svc"]["score"] < top["score"]


def test_auth_svc_is_not_blamed_just_because_everything_depends_on_it(acme_graph):
    # alerts from 4 services that all depend on auth-svc but would not explain auth-svc's other dependents
    r = call_tool(acme_graph, "rank_root_causes", {"alerting": ["web-gateway", "mobile-bff", "partner-api", "payments-api"], "top_k": 40}).data
    names = [c["candidate"] for c in r["candidates"]]
    assert names[0] == "payments-api"
    auth = next(c for c in r["candidates"] if c["candidate"] == "auth-svc")
    assert auth["coverage"] == 1.0 and auth["precision"] < 1.0 and auth["predicted_not_alerting"]


def test_async_lag_storm_finds_kafka(acme_graph):
    o = failure.break_service(get_world("acme"), "kafka", "infra", rng=random.Random(9))
    top = call_tool(acme_graph, "rank_root_causes", {"alerting": o.alerting}).data["candidates"][0]
    assert top["candidate"] == "kafka" and top["score"] == 1.0


def test_summary_sentence(acme_graph):
    o = failure.break_service(get_world("acme"), "ledger-db", "config", rng=random.Random(5))
    s = call_tool(acme_graph, "rank_root_causes", {"alerting": o.alerting}).data["candidates"][0]["summary"]
    assert s.startswith("ledger-db explains 11 of 11 alerts") and "fail silently" in s


def test_unknown_service_is_rejected(acme_graph):
    with pytest.raises(ValueError, match="unknown service"):
        call_tool(acme_graph, "rank_root_causes", {"alerting": ["nope"]})


def test_two_cause_storm_is_not_confidently_single():
    dev = [s for s in load_specs("dev") if s["tier"] == "ambiguous"]
    assert dev
    for spec in dev:
        w, o = materialize(spec)
        name = "t_amb"
        drop_graph(name)
        g = get_graph(name)
        load_world(g, w, now=NOW)
        r = call_tool(g, "rank_root_causes", {"alerting": o.alerting}).data
        assert r["weak_fit"] or r["likely_multiple_causes"]
        drop_graph(name)


@pytest.mark.parametrize("spec", [s for s in load_specs("dev") if s["tier"] != "ambiguous"], ids=lambda s: s["id"])
def test_dev_scenarios_true_cause_is_top1(spec):
    w, o = materialize(spec)
    name = "t_dev_" + spec["id"].replace("-", "_")
    drop_graph(name)
    g = get_graph(name)
    load_world(g, w, now=NOW)
    try:
        top = call_tool(g, "rank_root_causes", {"alerting": o.alerting}).data["candidates"]
        assert top[0]["candidate"] == spec["roots"][0], [(c["candidate"], c["score"]) for c in top]
    finally:
        drop_graph(name)
