import random

from backend.world import get_world, failure, topology as topo
from backend.world.scenarios import load_specs, materialize, generate_specs, PLAN


def test_hidden_culprit_does_not_alert():
    w = get_world("acme")
    o = failure.break_service(w, "ledger-db", "config", rng=random.Random(1))
    assert "ledger-db" not in o.alerting
    assert set(o.alerting) == {s for s in topo.sync_dependents(w, "ledger-db") if topo.svc_map(w)[s]["monitored"]}
    assert o.truth["silent_root"] and o.truth["root_causes"] == ["ledger-db"]


def test_monitored_root_alerts_itself():
    w = get_world("acme")
    o = failure.break_service(w, "payments-api", "code", rng=random.Random(1))
    assert "payments-api" in o.alerting and "web-gateway" in o.alerting


def test_async_dependents_get_delayed_lag_alerts():
    w = get_world("acme")
    o = failure.break_service(w, "kafka", "infra", rng=random.Random(2))
    assert set(o.lag_alerting) == {"ledger-svc", "notif-worker", "reporting-svc", "audit-svc", "orders-api"}
    lag_age = max(a["age_s"] for a in o.alerts if a["signal"] == "lag")
    sync_age = max(a["age_s"] for a in o.alerts if a["signal"] != "lag")
    assert lag_age <= sync_age   # lag alerts fire later (smaller age)


def test_trigger_deploy_20_to_60_min_before_first_alert():
    w = get_world("acme")
    for seed in range(20):
        o = failure.break_service(w, "ledger-db", "config", rng=random.Random(seed))
        gap = (o.deploys[0]["age_s"] - o.first_alert_age_s) / 60
        assert 20 <= gap <= 60


def test_noise_options():
    w = get_world("acme")
    o = failure.break_service(w, "ledger-db", "config", dict(flaky=True, missing=True, distractors=2), random.Random(3))
    assert o.truth["missing_alert"] not in o.alerting
    assert o.truth["flaky_alert"] in o.alerting
    assert len([d for d in o.deploys if d.get("distractor")]) == 2


def test_scenario_counts_and_tiers():
    for split, plan in PLAN.items():
        specs = load_specs(split)
        assert len(specs) == sum(plan.values())
        for tier, n in plan.items():
            assert sum(1 for s in specs if s["tier"] == tier) == n
    assert len(load_specs("dev")) == 10 and len(load_specs("test")) == 20


def test_scenarios_frozen():
    """The committed scenario files must equal what the generator produces: nobody tunes the test set."""
    assert generate_specs() == {s: load_specs(s) for s in ("dev", "test")}


def test_all_scenarios_materialize_with_ground_truth():
    for split in ("dev", "test"):
        for spec in load_specs(split):
            _, o = materialize(spec)
            assert o.alerts, spec["id"]
            assert set(o.truth["root_causes"]) == set(spec["roots"])
            if spec["tier"] == "ambiguous":
                assert len(spec["roots"]) == 2 and o.truth["multiple_causes"]
            if spec["tier"] == "easy":
                assert len(o.alerts) == 1
            if spec["tier"] in ("medium", "hard"):
                assert o.truth["silent_root"]


def test_dev_and_test_scenarios_are_distinct():
    ids = {s["id"] for s in load_specs("dev")} & {s["id"] for s in load_specs("test")}
    assert not ids
    seeds = {s["seed"] for s in load_specs("dev")} & {s["seed"] for s in load_specs("test")}
    assert not seeds
