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
