import json

import httpx
import pytest
from fastapi.testclient import TestClient

from backend.actions.discord import post_incident
from backend.app import main
from backend.app.limits import DailyCap, RateLimiter
from backend.graph import sandbox
from backend.graph.db import drop_graph


@pytest.fixture()
def client():
    main.limiter = RateLimiter(1000, 60)
    main.daily = DailyCap(1000)
    c = TestClient(main.app)
    yield c
    for n in sandbox.list_sandboxes():
        drop_graph(n)


def events(resp):
    return [json.loads(l[6:]) for l in resp.text.splitlines() if l.startswith("data: ")]


def test_full_flow_chaos_investigate_resolve(client):
    sb = client.post("/api/sandbox", json={"world": "acme"}).json()["sandbox"]
    g = client.get(f"/api/graph/{sb}").json()
    assert len(g["nodes"]) == 30 and g["alerting"] == [] and len(g["edges"]) == 60
    r = client.post("/api/chaos", json={"sandbox": sb, "service": "ledger-db", "change_kind": "config"}).json()
    assert r["n_alerts"] >= 5 and "ledger-db" not in r["alerting"]        # culprit stays hidden
    assert "culprit" not in json.dumps(r) and "root" not in json.dumps(r)
    assert client.get(f"/api/graph/{sb}").json()["alerting"] == sorted(r["alerting"])
    resp = client.post("/api/investigate", json={"sandbox": sb})
    ev = events(resp)
    assert ev[0]["type"] == "start" and ev[-1]["type"] == "done"
    res = ev[-1]["result"]
    assert res["root_cause"] == "ledger-db" and res["confidence"] == "high" and res["claims"]["rejected"] == 0
    ok = client.post("/api/resolve", json={"sandbox": sb, "investigation": res["investigation"], "action": "rollback", "ttr_min": 6}).json()
    assert ok["incident_id"].startswith("INC-")
    # next storm: the lesson learned a minute ago is now cited by History
    client.post("/api/chaos", json={"sandbox": sb, "service": "ledger-db", "change_kind": "config"})
    ev2 = events(client.post("/api/investigate", json={"sandbox": sb}))
    assert ev2[-1]["result"]["root_cause"] == "ledger-db"
    assert ev2[-1]["result"]["precedent"]


def test_surprise_me_and_unknown_inputs(client):
    sb = client.post("/api/sandbox", json={"world": "globex"}).json()["sandbox"]
    assert client.post("/api/chaos", json={"sandbox": sb, "surprise": True}).json()["n_alerts"] >= 4
    assert client.post("/api/chaos", json={"sandbox": sb, "service": "nope", "change_kind": "code"}).status_code == 400
    assert client.post("/api/chaos", json={"sandbox": sb, "service": "kafka", "change_kind": "drop table"}).status_code == 400
    assert client.post("/api/sandbox", json={"world": "evil"}).status_code == 400
    assert client.get("/api/graph/sbx_deadbeef").status_code == 404
    assert client.get("/api/graph/acme").status_code == 404                # templates are not reachable
    assert client.post("/api/investigate", json={"sandbox": "acme"}).status_code == 404


def test_no_alerts_no_investigation(client):
    sb = client.post("/api/sandbox", json={"world": "acme"}).json()["sandbox"]
    assert client.post("/api/investigate", json={"sandbox": sb}).status_code == 400


def test_rate_limit_and_daily_cap_replay(client):
    main.daily = DailyCap(0)
    sb = client.post("/api/sandbox", json={"world": "acme"}).json()["sandbox"]
    client.post("/api/chaos", json={"sandbox": sb, "service": "ledger-db", "change_kind": "config"})
    ev = events(client.post("/api/investigate", json={"sandbox": sb}))
    assert ev[0]["type"] == "notice" and all(e.get("replay") for e in ev) and ev[-1]["type"] == "done"
    main.limiter = RateLimiter(2, 60)
    main.limiter = RateLimiter(2, 60)
    assert [client.post("/api/sandbox", json={"world": "acme"}).status_code for _ in range(3)] == [200, 200, 429]
    assert main.limiter.allow("1.2.3.4") and main.limiter.allow("1.2.3.4") and not main.limiter.allow("1.2.3.4")


def test_post_uses_server_text_and_discord_validation(client, monkeypatch):
    sent = []
    monkeypatch.setattr(main, "post_incident", lambda msg: sent.append(msg) or dict(posted=True, channel="#incidents"))
    sb = client.post("/api/sandbox", json={"world": "acme"}).json()["sandbox"]
    client.post("/api/chaos", json={"sandbox": sb, "service": "ledger-db", "change_kind": "config"})
    inv = events(client.post("/api/investigate", json={"sandbox": sb}))[-1]["result"]["investigation"]
    r = client.post("/api/post", json={"sandbox": sb, "investigation": inv, "message": "@everyone buy crypto"}).json()
    assert r["posted"] and len(sent) == 1 and "@everyone" not in sent[0] and "ledger-db" in sent[0]
    assert client.post("/api/post", json={"sandbox": sb, "investigation": "inv-99"}).status_code == 404


def test_discord_webhook_rules():
    assert post_incident("hi", webhook_url="")["posted"] is False
    assert post_incident("hi", webhook_url="https://evil.example.com/api/webhooks/1/abc")["reason"].startswith("webhook URL")
    seen = {}

    def handler(req):
        seen["body"] = json.loads(req.content)
        return httpx.Response(204)
    ok = post_incident("x" * 5000, webhook_url="https://discord.com/api/webhooks/123/abc-DEF", transport=httpx.MockTransport(handler))
    assert ok["posted"] and len(seen["body"]["content"]) <= 1900 and seen["body"]["allowed_mentions"] == {"parse": []}
    bad = post_incident("x", webhook_url="https://discord.com/api/webhooks/123/abc", transport=httpx.MockTransport(lambda r: httpx.Response(500)))
    assert bad["posted"] is False


def test_again_whatif_late_and_calm_after_resolve(client):
    sb = client.post("/api/sandbox", json={"world": "acme"}).json()["sandbox"]
    assert client.post("/api/chaos", json={"sandbox": sb, "again": True}).status_code == 400          # nothing to repeat yet
    assert client.post("/api/late", json={"sandbox": sb}).status_code == 400
    w = client.post("/api/whatif", json={"sandbox": sb, "service": "ledger-db"}).json()
    assert w["arr"] > 0 and "ledger-svc" in w["failing_now"]
    assert client.post("/api/whatif", json={"sandbox": sb, "service": "nope"}).status_code == 400
    client.post("/api/chaos", json={"sandbox": sb, "surprise": True})
    res = events(client.post("/api/investigate", json={"sandbox": sb}))[-1]["result"]
    lr = client.post("/api/late", json={"sandbox": sb})
    if lr.status_code == 200:                         # surprise mode drops some alerts, so usually something arrives late
        ev = events(lr)
        assert ev[0]["type"] == "start" and ev[-1]["type"] == "done" and ev[-1]["result"]["ripple"]["new_alerts"]
        res = ev[-1]["result"]
    else:
        assert lr.status_code == 409
    client.post("/api/resolve", json={"sandbox": sb, "investigation": res["investigation"], "action": "restart", "ttr_min": 9})
    assert client.get(f"/api/graph/{sb}").json()["alerting"] == []                                 # calm map after resolving
    again = client.post("/api/chaos", json={"sandbox": sb, "again": True}).json()
    assert again["n_alerts"] >= 1
    res2 = events(client.post("/api/investigate", json={"sandbox": sb}))[-1]["result"]
    assert res2["root_cause"] == res["root_cause"] and res2["precedent"]                          # memory: the lesson is cited


COMPOSE = """
services:
  web: {build: ., ports: ["80:80"], depends_on: [api], healthcheck: {test: ["CMD", "true"]}}
  api: {build: ./api, depends_on: [db, cache], healthcheck: {test: ["CMD", "true"]}}
  worker: {build: ./w, depends_on: [db], healthcheck: {test: ["CMD", "true"]}}
  db: {image: postgres:16}
  cache: {image: redis:7, healthcheck: {test: ["CMD", "true"]}}
"""


def test_bring_your_own_compose(client):
    assert client.post("/api/import", json={"compose": "version: '3' # nothing"}).status_code == 400
    r = client.post("/api/import", json={"compose": COMPOSE}).json()
    sb = r["sandbox"]
    assert r["services"] == 5 and any("db" in n for n in r["notes"])
    g = client.get(f"/api/graph/{sb}").json()
    assert len(g["nodes"]) == 5
    c = client.post("/api/chaos", json={"sandbox": sb, "service": "db", "change_kind": "config"}).json()
    assert set(c["alerting"]) == {"web", "api", "worker"}
    res = events(client.post("/api/investigate", json={"sandbox": sb}))[-1]["result"]
    assert res["root_cause"] == "db" and res["claims"]["rejected"] == 0
    assert client.post("/api/chaos", json={"sandbox": sb, "surprise": True}).status_code == 200


def test_ask_the_graph_checks_citations(client, monkeypatch):
    from backend.agents.llm import Reply
    sb = client.post("/api/sandbox", json={"world": "acme"}).json()["sandbox"]
    monkeypatch.setattr(main, "make_ask_client", lambda: None)
    assert client.post("/api/ask", json={"sandbox": sb, "question": "who owns redis-cache?"}).status_code == 503

    class Fake:
        provider = "anthropic"

        def complete(self, model, system, messages, tools=None, **kw):
            if len(messages) == 1:
                return Reply(tool_calls=[dict(id="1", name="find_experts", args={"service": "redis-cache"})])
            return Reply(text='{"answer": "Platform team owns it.", "cites": ["Service:redis-cache", "Person:nobody"]}')
    monkeypatch.setattr(main, "make_ask_client", lambda: Fake())
    r = client.post("/api/ask", json={"sandbox": sb, "question": "who owns redis-cache?"}).json()
    assert r["answer"].startswith("Platform") and r["cites"] == ["Service:redis-cache"] and r["rejected"] == 1
    assert r["calls"][0]["tool"] == "find_experts" and r["services"] == ["redis-cache"]
    assert client.post("/api/ask", json={"sandbox": sb, "question": "x" * 400}).status_code == 422


def test_postmortem_from_graph(client):
    sb = client.post("/api/sandbox", json={"world": "acme"}).json()["sandbox"]
    client.post("/api/chaos", json={"sandbox": sb, "service": "ledger-db", "change_kind": "config"})
    res = events(client.post("/api/investigate", json={"sandbox": sb}))[-1]["result"]
    client.post("/api/resolve", json={"sandbox": sb, "investigation": res["investigation"], "action": "rollback", "ttr_min": 7})
    md = client.get(f"/api/postmortem/{sb}/{res['investigation']}").json()["markdown"]
    assert md.startswith("# Postmortem: ledger-db") and "## Timeline" in md and "resolved by rollback" in md
    assert "Lesson saved to memory" in md and "Add monitoring to ledger-db" in md
    assert client.get(f"/api/postmortem/{sb}/inv-999").status_code == 404
    assert client.get(f"/api/postmortem/{sb}/../x").status_code in (400, 404)


def test_ready_and_db_health(client):
    r = client.get("/api/ready")
    assert r.status_code == 200 and r.json()["ready"] is True
    h = client.get("/api/health?db=1").json()
    assert h["ok"] and h["db"] == "ok" and "sandboxes" in h
    assert "db" not in client.get("/api/health").json()          # plain liveness never touches the database


def test_ready_reports_db_down(client, monkeypatch):
    class Dead:
        class connection:
            @staticmethod
            def ping():
                raise ConnectionError("down")
    monkeypatch.setattr(main, "get_db", lambda: Dead)
    r = client.get("/api/ready")
    assert r.status_code == 503 and r.json()["state"] == "db_unavailable"
