import json

import httpx
import pytest

from backend.agents.llm import ChatClient, LLMError, client_from_env, model_for, run_tool_loop

TOOL = [dict(name="blast_radius", description="d", input_schema={"type": "object", "properties": {"service": {"type": "string"}}, "required": ["service"]})]


def transport(responses, seen):
    it = iter(responses)

    def handler(req):
        seen.append(dict(url=str(req.url), headers=dict(req.headers), body=json.loads(req.content)))
        return httpx.Response(200, json=next(it))
    return httpx.MockTransport(handler)


def test_anthropic_tool_loop_and_request_shape():
    seen = []
    t = transport([
        {"content": [{"type": "text", "text": "checking"}, {"type": "tool_use", "id": "t1", "name": "blast_radius", "input": {"service": "kafka"}}],
         "usage": {"input_tokens": 100, "output_tokens": 20, "cache_read_input_tokens": 60}, "stop_reason": "tool_use"},
        {"content": [{"type": "text", "text": "done"}], "usage": {"input_tokens": 150, "output_tokens": 5}, "stop_reason": "end_turn"}], seen)
    c = ChatClient("anthropic", "sk-test", t)
    ran = []
    text, usage, steps = run_tool_loop(c, "claude-haiku-5-5", "SYS", "go", TOOL, lambda n, a: ran.append((n, a)) or '{"ok":1}')
    assert text == "done" and steps == 2 and ran == [("blast_radius", {"service": "kafka"})]
    assert usage == {"input": 250, "output": 25, "cache_read": 60}
    first, second = seen
    assert first["url"].endswith("/v1/messages") and first["headers"]["x-api-key"] == "sk-test"
    assert first["body"]["system"][0]["cache_control"] == {"type": "ephemeral"} and first["body"]["temperature"] == 0.0
    assert first["body"]["tools"][0]["input_schema"]["required"] == ["service"]
    assert second["body"]["messages"][-1]["content"][0] == {"type": "tool_result", "tool_use_id": "t1", "content": '{"ok":1}'}


def test_openrouter_tool_loop_and_request_shape():
    seen = []
    t = transport([
        {"choices": [{"message": {"content": None, "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "blast_radius", "arguments": '{"service":"kafka"}'}}]}, "finish_reason": "tool_calls"}],
         "usage": {"prompt_tokens": 90, "completion_tokens": 10}},
        {"choices": [{"message": {"content": "all good"}, "finish_reason": "stop"}], "usage": {"prompt_tokens": 120, "completion_tokens": 4}}], seen)
    c = ChatClient("openrouter", "or-test", t)
    text, usage, steps = run_tool_loop(c, "some/model", "SYS", "go", TOOL, lambda n, a: "{}")
    assert text == "all good" and steps == 2 and usage["input"] == 210
    assert seen[0]["url"] == "https://openrouter.ai/api/v1/chat/completions" and seen[0]["headers"]["authorization"] == "Bearer or-test"
    assert seen[0]["body"]["messages"][0] == {"role": "system", "content": "SYS"}
    assert seen[0]["body"]["tools"][0]["function"]["name"] == "blast_radius"
    assert seen[1]["body"]["messages"][-1] == {"role": "tool", "tool_call_id": "c1", "content": "{}"}


def test_bad_tool_arguments_and_tool_errors_do_not_crash():
    seen = []
    t = transport([
        {"choices": [{"message": {"tool_calls": [{"id": "c1", "type": "function", "function": {"name": "x", "arguments": "{not json"}}]}}]},
        {"choices": [{"message": {"content": "ok"}}]}], seen)
    c = ChatClient("openrouter", "k", t)

    def boom(n, a):
        assert a == {}
        raise ValueError("nope")
    text, _, _ = run_tool_loop(c, "m", "S", "u", TOOL, boom)
    assert text == "ok" and "nope" in seen[1]["body"]["messages"][-1]["content"]


def test_step_budget_stops_runaway_loops():
    always_tool = {"choices": [{"message": {"tool_calls": [{"id": "c", "type": "function", "function": {"name": "x", "arguments": "{}"}}]}}]}
    seen = []
    c = ChatClient("openrouter", "k", transport([always_tool] * 10, seen))
    text, _, steps = run_tool_loop(c, "m", "S", "u", TOOL, lambda n, a: "{}", max_steps=3)
    assert text == "" and steps == 3 and len(seen) == 3


def test_errors_and_key_hygiene(monkeypatch):
    c = ChatClient("anthropic", "sk-secret", httpx.MockTransport(lambda r: httpx.Response(429, text="rate limited")))
    with pytest.raises(LLMError, match="429"):
        c.complete("m", "s", [{"role": "user", "text": "hi"}])
    assert "sk-secret" not in repr(c) and "sk-secret" not in str(c)
    with pytest.raises(LLMError, match="no API key"):
        ChatClient("openrouter", "")
    with pytest.raises(LLMError, match="unknown provider"):
        ChatClient("evil", "k")
    for k in ("ANTHROPIC_API_KEY", "OPENROUTER_API_KEY", "LLM_PROVIDER", "LEAD_MODEL", "AGENT_MODEL"):
        monkeypatch.delenv(k, raising=False)
    with pytest.raises(LLMError):
        client_from_env()
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    assert client_from_env().provider == "openrouter"
    with pytest.raises(LLMError, match="LEAD_MODEL"):
        model_for("lead", "openrouter")
    monkeypatch.setenv("AGENT_MODEL", "x/y")
    assert model_for("agent", "openrouter") == "x/y" and model_for("lead", "anthropic") == "claude-sonnet-5-5"
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k2")
    assert client_from_env().provider == "anthropic"


def test_generic_openai_compatible_provider_uses_base_url(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("LLM_BASE_URL", "https://example.test/v1/chat/completions")
    monkeypatch.setenv("LLM_API_KEY", "k-test")
    seen = []
    t = transport([{"choices": [{"message": {"content": "hi"}, "finish_reason": "stop"}], "usage": {"prompt_tokens": 3, "completion_tokens": 1}}], seen)
    c = client_from_env(t)
    assert c.complete("gemini-x", "sys", [{"role": "user", "text": "yo"}]).text == "hi"
    assert seen[0]["url"] == "https://example.test/v1/chat/completions" and seen[0]["headers"]["authorization"] == "Bearer k-test"
    monkeypatch.delenv("LLM_BASE_URL")
    with pytest.raises(LLMError):
        client_from_env(t)
