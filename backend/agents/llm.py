"""A small, swappable model layer: Anthropic Messages API or any OpenAI-compatible API (OpenRouter).

Both are normalised to one shape so the agents do not care which is used:
    client.complete(model, system, messages, tools, max_tokens, temperature) -> Reply(text, tool_calls, usage, stop)
Messages use a neutral format:
    {"role": "user", "text": "..."}
    {"role": "assistant", "text": "...", "tool_calls": [{"id", "name", "args"}]}
    {"role": "tool", "results": [{"id", "name", "content": "..."}]}
The key is read from the environment only (ANTHROPIC_API_KEY or OPENROUTER_API_KEY) and is never logged.
"""
import json
import os
from dataclasses import dataclass, field

import httpx

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_MODELS = {"anthropic": {"lead": "claude-sonnet-5-5", "agent": "claude-haiku-5-5"}}


class LLMError(RuntimeError):
    pass


@dataclass
class Reply:
    text: str = ""
    tool_calls: list = field(default_factory=list)
    usage: dict = field(default_factory=lambda: {"input": 0, "output": 0, "cache_read": 0})
    stop: str = ""


def _safe_json(s):
    try:
        v = json.loads(s) if isinstance(s, str) else (s or {})
        return v if isinstance(v, dict) else {}
    except ValueError:
        return {}


class ChatClient:
    def __init__(self, provider, api_key, transport=None, timeout=60):
        if provider not in ("anthropic", "openrouter", "openai"):
            raise LLMError(f"unknown provider {provider!r}")
        if not api_key:
            raise LLMError("no API key configured")
        self.provider, self._key, self._transport, self._timeout = provider, api_key, transport, timeout

    def __repr__(self):                                  # never print the key
        return f"ChatClient(provider={self.provider!r})"

    # ---- public --------------------------------------------------------------------------------------------
    def complete(self, model, system, messages, tools=None, max_tokens=1024, temperature=0.0) -> Reply:
        if self.provider == "anthropic":
            url, headers, body = ANTHROPIC_URL, {"x-api-key": self._key, "anthropic-version": "2023-06-01"}, self._anthropic_body(model, system, messages, tools, max_tokens, temperature)
        else:
            url, headers, body = (os.environ.get("LLM_BASE_URL", "").strip() if self.provider == "openai" else OPENROUTER_URL), {"Authorization": f"Bearer {self._key}"}, self._openai_body(model, system, messages, tools, max_tokens, temperature)
        with httpx.Client(transport=self._transport, timeout=self._timeout) as c:
            r = c.post(url, headers=headers, json=body)
        if r.status_code >= 400:
            raise LLMError(f"{self.provider} returned {r.status_code}: {r.text[:200]}")
        data = r.json()
        return self._parse_anthropic(data) if self.provider == "anthropic" else self._parse_openai(data)

    # ---- Anthropic -----------------------------------------------------------------------------------------
    def _anthropic_body(self, model, system, messages, tools, max_tokens, temperature):
        msgs = []
        for m in messages:
            if m["role"] == "user":
                msgs.append({"role": "user", "content": m["text"]})
            elif m["role"] == "assistant":
                blocks = ([{"type": "text", "text": m["text"]}] if m.get("text") else []) + [
                    {"type": "tool_use", "id": t["id"], "name": t["name"], "input": t["args"]} for t in m.get("tool_calls", [])]
                msgs.append({"role": "assistant", "content": blocks})
            else:
                msgs.append({"role": "user", "content": [{"type": "tool_result", "tool_use_id": r["id"], "content": r["content"]} for r in m["results"]]})
        # current Claude models reject `temperature` (deprecated), so it is only sent when ANTHROPIC_SEND_TEMPERATURE=1
        body = {"model": model, "max_tokens": max_tokens, "messages": msgs,
                # the system prompt is cached: it is identical on every call of an investigation
                "system": [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}]}
        if os.environ.get("ANTHROPIC_SEND_TEMPERATURE") == "1" and temperature is not None:
            body["temperature"] = temperature
        if tools:
            body["tools"] = [{"name": t["name"], "description": t["description"], "input_schema": t["input_schema"]} for t in tools]
        return body

    def _parse_anthropic(self, d):
        text = "".join(b.get("text", "") for b in d.get("content", []) if b.get("type") == "text")
        calls = [dict(id=b["id"], name=b["name"], args=b.get("input") or {}) for b in d.get("content", []) if b.get("type") == "tool_use"]
        u = d.get("usage", {})
        return Reply(text, calls, {"input": u.get("input_tokens", 0), "output": u.get("output_tokens", 0), "cache_read": u.get("cache_read_input_tokens", 0)}, d.get("stop_reason", ""))

    # ---- OpenAI-compatible (OpenRouter) --------------------------------------------------------------------
    def _openai_body(self, model, system, messages, tools, max_tokens, temperature):
        msgs = [{"role": "system", "content": system}]
        for m in messages:
            if m["role"] == "user":
                msgs.append({"role": "user", "content": m["text"]})
            elif m["role"] == "assistant":
                e = {"role": "assistant", "content": m.get("text") or None}
                if m.get("tool_calls"):
                    e["tool_calls"] = [{"id": t["id"], "type": "function", "function": {"name": t["name"], "arguments": json.dumps(t["args"])}} for t in m["tool_calls"]]
                msgs.append(e)
            else:
                msgs += [{"role": "tool", "tool_call_id": r["id"], "content": r["content"]} for r in m["results"]]
        body = {"model": model, "max_tokens": max_tokens, "temperature": temperature, "messages": msgs}
        if tools:
            body["tools"] = [{"type": "function", "function": {"name": t["name"], "description": t["description"], "parameters": t["input_schema"]}} for t in tools]
        return body

    def _parse_openai(self, d):
        ch = (d.get("choices") or [{}])[0]
        m = ch.get("message", {})
        calls = [dict(id=t["id"], name=t["function"]["name"], args=_safe_json(t["function"].get("arguments"))) for t in (m.get("tool_calls") or [])]
        u = d.get("usage", {})
        return Reply(m.get("content") or "", calls, {"input": u.get("prompt_tokens", 0), "output": u.get("completion_tokens", 0), "cache_read": 0}, ch.get("finish_reason", ""))


def client_from_env(transport=None) -> ChatClient:
    """LLM_PROVIDER = anthropic | openrouter; default: whichever key is set (Anthropic first)."""
    provider = os.environ.get("LLM_PROVIDER", "").strip().lower()
    if not provider:
        provider = "anthropic" if os.environ.get("ANTHROPIC_API_KEY") else "openrouter"
    # provider "openai" = any OpenAI-compatible chat-completions endpoint (e.g. Google AI Studio's free Gemini key):
    #   LLM_PROVIDER=openai  LLM_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai/chat/completions  LLM_API_KEY=...
    key = os.environ.get({"anthropic": "ANTHROPIC_API_KEY", "openai": "LLM_API_KEY"}.get(provider, "OPENROUTER_API_KEY"), "")
    if provider == "openai" and not os.environ.get("LLM_BASE_URL", "").strip():
        raise LLMError("set LLM_BASE_URL to the chat-completions URL of your provider")
    return ChatClient(provider, key, transport)


def model_for(role: str, provider: str) -> str:
    """role = 'lead' | 'agent'. LEAD_MODEL / AGENT_MODEL always win; OpenRouter has no default (ids differ per model)."""
    env = os.environ.get("LEAD_MODEL" if role == "lead" else "AGENT_MODEL", "").strip()
    if env:
        return env
    if provider in DEFAULT_MODELS:
        return DEFAULT_MODELS[provider][role]
    raise LLMError(f"set {'LEAD_MODEL' if role == 'lead' else 'AGENT_MODEL'} (a model id from your provider)")


def run_tool_loop(client, model, system, user_text, tools, execute, max_steps=8, max_output_tokens=4000, temperature=0.0, max_tokens_per_call=2048):
    """Let a model call tools until it answers. `execute(name, args) -> str` runs a tool (the caller enforces scoping).
    Budgets: at most `max_steps` model calls and `max_output_tokens` total output tokens. Returns (final_text, usage, steps)."""
    messages = [{"role": "user", "text": user_text}]
    usage = {"input": 0, "output": 0, "cache_read": 0}
    for step in range(1, max_steps + 1):
        rep = client.complete(model, system, messages, tools, max_tokens=max_tokens_per_call, temperature=temperature)
        for k in usage:
            usage[k] += rep.usage.get(k, 0)
        if not rep.tool_calls:
            return rep.text, usage, step
        messages.append({"role": "assistant", "text": rep.text, "tool_calls": rep.tool_calls})
        results = []
        for t in rep.tool_calls:
            try:
                out = execute(t["name"], t["args"])
            except Exception as e:                       # tell the model what went wrong so it can fix its call
                out = json.dumps({"error": str(e)[:300]})
            results.append(dict(id=t["id"], name=t["name"], content=out if isinstance(out, str) else json.dumps(out, default=str)))
        messages.append({"role": "tool", "results": results})
        if usage["output"] >= max_output_tokens:
            break
    return "", usage, step                                # budget exhausted: caller treats an empty answer as "no finding"
