"""LLM policy tested with a scripted fake model (no API key, no network). DEV scenarios only."""
import json
import re

import pytest

from backend.agents.llm import Reply
from backend.agents.llm_policy import LLMPolicy
from backend.agents.runner import run_investigation
from backend.graph.db import drop_graph, get_graph
from backend.tests.conftest import NOW
from backend.world import failure
from backend.world.loader import load_world
from backend.world.scenarios import load_specs, materialize

DEV = {s["id"]: s for s in load_specs("dev")}
TOOL_FOR = {"Impact": "blast_radius", "Changes": "recent_changes", "History": "similar_incidents", "People": "find_experts"}


class FakeModel:
    """Plays all roles. Specialists: call their tool once per hypothesis, then write one finding per hypothesis citing a real id."""
    provider = "anthropic"

    def __init__(self, lead=None, bad_cite=False, junk_for=None):
        self.lead, self.bad_cite, self.junk_for, self.calls = lead, bad_cite, junk_for, 0

    def complete(self, model, system, messages, tools=None, max_tokens=1024, temperature=0.0):
        self.calls += 1
        usage = {"input": 100, "output": 20, "cache_read": 0}
        if not tools:                                           # the Lead
            return Reply(text=json.dumps(self.lead(messages[0]["text"])), usage=usage)
        agent = next(a for a in TOOL_FOR if a in system.split("\n")[0])
        if self.junk_for == agent:
            return Reply(text="I cannot do this", usage=usage)
        hyps = re.findall(r"- (h-\S+): service (\S+)", messages[0]["text"])
        if len(messages) == 1:
            calls = []
            for i, (_, svc) in enumerate(hyps):
                args = {"services": [svc], "until_ts": int(re.search(r"First alert \(unix\): (\d+)", messages[0]["text"]).group(1)), "window_minutes": 120} if agent == "Changes" \
                    else ({"service": svc, "at_time": NOW} if agent == "People" else {"service": svc})
                calls.append(dict(id=f"c{i}", name=TOOL_FOR[agent], args=args))
            return Reply(tool_calls=calls, usage=usage)
        results = messages[-1]["results"]
        findings = []
        for (hid, svc), r in zip(hyps, results):
            ids = json.loads(r["content"])["cite_ids"]
            cites = ["Service:not-a-real-service"] if self.bad_cite else [f"Service:{svc}"]
            assert f"Service:{svc}" in ids
            findings.append(dict(hypothesis_id=hid, supports=True, text=f"{agent} looked at {svc}", cites=cites))
        return Reply(text=json.dumps(dict(findings=findings)), usage=usage)


def setup(sid):
    world, o = materialize(DEV[sid])
    name = "t_llm_" + sid.replace("-", "_")
    drop_graph(name)
    g = get_graph(name)
    load_world(g, world, now=NOW)
    failure.apply_outcome(g, o, NOW)
    return g, o


def pick_top(text):
    return json.loads(text.split("Board:\n")[1])[0]["service"]


def test_model_policy_end_to_end_with_real_citations():
    g, o = setup("dev-easy-1")
    fake = FakeModel(lead=lambda t: dict(root_cause=pick_top(t), confidence="high", reasons=["It fits and a change lines up."]))
    pol = LLMPolicy(client=fake, lead_model="L", agent_model="A")
    res = run_investigation(g, o.alerting, now=NOW, policy=pol)
    assert res["root_cause"] == o.roots[0]
    assert res["claims"]["rejected"] == 0 and res["claims"]["verified"] >= 4
    assert res["confidence"] in ("high", "medium")
    assert pol.usage["agent"]["input"] > 0 and pol.usage["lead"]["output"] == 20 and pol.cost_usd() > 0
    assert res["verification"] is not None            # the proposed fix was simulated against the graph


def test_invented_citations_are_rejected_not_stored():
    g, o = setup("dev-easy-1")
    fake = FakeModel(lead=lambda t: dict(root_cause=pick_top(t), confidence="high", reasons=["x"]), bad_cite=True)
    events = []
    res = run_investigation(g, o.alerting, now=NOW, policy=LLMPolicy(client=fake, lead_model="L", agent_model="A"), emit=events.append)
    assert res["claims"]["rejected"] > 0
    assert any(e["type"] == "notice" and "citation check" in e["text"] for e in events)
    assert res["confidence"] != "high"                 # no supporting evidence survived, so high is impossible


def test_high_confidence_is_clamped_without_evidence_kinds():
    g, o = setup("dev-easy-1")
    fake = FakeModel(lead=lambda t: dict(root_cause=pick_top(t), confidence="high", reasons=["trust me"]), junk_for="Changes")
    pol = LLMPolicy(client=fake, lead_model="L", agent_model="A")
    res = run_investigation(g, o.alerting, now=NOW, policy=pol)
    assert any("Changes" in n for n in pol.notes)       # fell back to rules for that specialist, said so
    assert res["root_cause"] == o.roots[0]


def test_bad_lead_json_falls_back_to_rules():
    g, o = setup("dev-easy-1")

    class Broken(FakeModel):
        def complete(self, model, system, messages, tools=None, **kw):
            if not tools:
                return Reply(text="no json here")
            return super().complete(model, system, messages, tools, **kw)
    pol = LLMPolicy(client=Broken(), lead_model="L", agent_model="A")
    res = run_investigation(g, o.alerting, now=NOW, policy=pol)
    assert res["root_cause"] == o.roots[0] and any("Lead" in n for n in pol.notes)


def test_structural_abstention_cannot_be_overridden_by_the_model():
    g, o = setup("dev-ambiguous-1")
    fake = FakeModel(lead=lambda t: dict(root_cause=pick_top(t), confidence="high", reasons=["confident!"]))
    res = run_investigation(g, o.alerting, now=NOW, policy=LLMPolicy(client=fake, lead_model="L", agent_model="A"))
    assert res["root_cause"] in (None, "undetermined") and res["confidence"] == "low"


def test_model_naming_a_service_off_the_board_is_ignored():
    g, o = setup("dev-easy-1")
    fake = FakeModel(lead=lambda t: dict(root_cause="made-up-svc", confidence="high", reasons=["x"]))
    res = run_investigation(g, o.alerting, now=NOW, policy=LLMPolicy(client=fake, lead_model="L", agent_model="A"))
    assert res["root_cause"] == o.roots[0]
