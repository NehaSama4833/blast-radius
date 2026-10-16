from backend.agents.faithful import check, numbers_in

SVCS = ["ledger-db", "ledger-svc", "auth-v2"]


def test_numbers_pool_includes_lengths_percent_and_strings():
    pool = numbers_in({"explains": ["a"] * 11, "score": 0.9091, "arr": 5983000, "summary": "shipped 56 min before"})
    assert {"11", "91", "5983000", "56"} <= pool


def test_flags_unseen_names_and_numbers_only():
    seen = {"Service:ledger-db", "Deploy:d-477", "Incident:INC-124"}
    pool = numbers_in({"m": 56, "arr": 5983000, "n": ["x"] * 11})
    ok = check("ledger-db: deploy d-477 shipped 56 min before; same as INC-124; ARR 5,983,000; 11 alerts; 3 findings", seen, pool, SVCS)
    assert ok["flagged"] == [] and ok["names"] == 3 and ok["numbers"] == 3
    bad = check("ledger-svc broke after d-999, costing $42,000; auth-v2 is fine", seen, pool, SVCS)
    assert any("ledger-svc" in f for f in bad["flagged"]) and any("d-999" in f for f in bad["flagged"])
    assert any("42,000" in f for f in bad["flagged"]) and not any(f.startswith("number 2") for f in bad["flagged"])
