import pytest

from bench.docs import BM25, DocStore, render_docs
from bench.metrics import aggregate, score_one
from bench import run as bench_run
from backend.world import failure, get_world, topology as topo
from backend.world.scenarios import load_specs, materialize


def test_docs_contain_the_same_facts_as_the_graph():
    w = get_world("acme")
    docs = render_docs(w)
    assert len([p for p in docs if p.startswith("services/")]) == 30
    assert "NOT monitored" in docs["services/ledger-db.md"] and "monitored." in docs["services/payments-api.md"]
    for d in w["deps"]:
        assert f"- {d['dst']} ({d['kind']})" in docs[f"services/{d['src']}.md"]
    assert all(f"- {d['dst']}" in docs[f"services/{d['src']}.md"] for d in w["deps"])
    assert len([p for p in docs if p.startswith("postmortems/")]) == len(w["incidents"])
    assert docs["deploys/log.md"].count("\n- d-") == len(w["deploys"])
    # the docs never contain the answer: there is no 'root cause' of the CURRENT storm anywhere
    spec = [s for s in load_specs("dev") if s["id"] == "dev-hard-2"][0]
    world, o = materialize(spec)
    live = render_docs(world, o)
    assert "alerts/active.md" in live and all(a["id"] in live["alerts/active.md"] for a in o.alerts)
    assert o.truth["deploy_ids"][0] in live["deploys/log.md"]
    assert "ground truth" not in " ".join(live.values()).lower()


def test_bm25_ranks_relevant_page_first():
    docs = render_docs(get_world("acme"))
    store = DocStore(docs)
    hits = store.search_docs("connection pool exhausted ledger-db rollback", k=3)
    assert hits[0]["path"].startswith("postmortems/") and "pool" in docs[hits[0]["path"]].lower()
    assert store.search_docs("zzzzqqq") == []
    assert "Depends on" in store.read_doc("services/payments-api.md")
    with pytest.raises(ValueError):
        store.read_doc("../../etc/passwd")
    assert BM25({"a": "alpha beta", "b": "beta gamma"}).search("alpha")[0][1] == "a"


def res(rc, conf="high", hyps=(), deploy=None, rejected=0):
    return dict(root_cause=rc, confidence=conf, hypotheses=[dict(service=h) for h in hyps], blames_deploy=deploy,
                claims=dict(verified=10, rejected=rejected), duration_s=1.0, tokens=100)


def test_metrics_golden():
    spec = dict(id="s1", tier="medium", world="acme")
    truth = dict(root_causes=["ledger-db"], deploy_ids=["d-9"])
    ok = score_one(spec, truth, res("ledger-db", hyps=["ledger-db"], deploy="d-9"))
    assert ok["top1"] and ok["top3"] and ok["deploy_found"] and not ok["confident_and_wrong"]
    wrong = score_one(spec, truth, res("kafka", hyps=["kafka", "ledger-db"], deploy="d-1", rejected=2))
    assert not wrong["top1"] and wrong["top3"] and wrong["confident_and_wrong"] and wrong["invalid_citations"] == 2
    ab = score_one(spec, truth, res("undetermined", "low"))
    assert ab["wrong_abstention"] and not ab["top1"]
    amb_spec = dict(id="s2", tier="ambiguous", world="acme")
    amb_truth = dict(root_causes=["kafka", "fraud-store"], deploy_ids=["d-1", "d-2"], multiple_causes=True)
    assert score_one(amb_spec, amb_truth, res("undetermined", "low"))["correct_abstention"]
    assert score_one(amb_spec, amb_truth, res("kafka", "high"))["confident_and_wrong"]


def test_aggregate_and_calibration():
    truth = dict(root_causes=["a"], deploy_ids=["d"])
    rows = [score_one(dict(id=str(i), tier="easy", world="acme"), truth, res("a" if i < 3 else "b", "high" if i < 2 else "low", ["a"], "d")) for i in range(4)]
    agg = aggregate(rows)
    assert agg["all"]["top1"] == 0.75 and agg["easy"]["n"] == 4 and agg["calibration"]["high"] == dict(n=2, correct=1.0)
    assert agg["calibration"]["low"] == dict(n=2, correct=0.5)


def test_test_split_is_refused_without_final(tmp_path):
    with pytest.raises(SystemExit):
        bench_run.main(["--split", "test"])
    assert not list(bench_run.RESULTS.glob("test-*"))


def test_dev_run_end_to_end(tmp_path):
    out = tmp_path / "r.json"
    rep = bench_run.main(["--split", "dev", "--out", str(out)])
    assert out.exists() and rep["summary"]["all"]["n"] == 10 and rep["summary"]["all"]["invalid_citations"] == 0


def test_docs_only_baseline_with_fake_model():
    import json
    from backend.agents.llm import Reply
    from bench.baseline import run_docs_agent
    from backend.world.scenarios import load_specs, materialize
    spec = load_specs("dev")[0]
    world, o = materialize(spec)

    class Fake:
        provider = "anthropic"

        def complete(self, model, system, messages, tools=None, **kw):
            if len(messages) == 1:
                return Reply(tool_calls=[dict(id="1", name="search_docs", args=dict(query="deploy log " + o.roots[0]))], usage={"input": 10, "output": 5, "cache_read": 0})
            return Reply(text=json.dumps(dict(root_cause=o.roots[0], confidence="medium", top3=[o.roots[0]], deploy_id=None,
                                              cites=["deploys/log.md", "docs/never-opened.md"])), usage={"input": 10, "output": 5, "cache_read": 0})
    r = run_docs_agent(world, o, 1_800_000_000, client=Fake(), lead_model="m")
    assert r["root_cause"] == o.roots[0] and r["tokens"] == 30
    assert r["claims"]["rejected"] >= 1          # a citation to a doc it never opened is rejected
