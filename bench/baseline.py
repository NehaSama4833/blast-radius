"""Condition B: the SAME facts as Markdown docs, a keyword (BM25) search tool and a read tool, one model, no graph.

It gets the same alert list and the same model family as condition A. It does not get dependency traversal,
root-cause ranking, simulation or memory. The agent must cite doc paths; a citation counts as valid only if it opened or
searched that doc (same rule as the graph agents' citation check).
"""
import json
import re
import time

from backend.agents.llm import client_from_env, model_for, run_tool_loop
from bench.docs import DocStore, render_docs

SYSTEM = """You are an on-call engineer. Several services are alerting. Using ONLY the documentation tools, find the most likely root cause service (it may itself have no alerts), and the deploy that caused it if any.
Tools: search_docs(query) keyword search over runbooks, postmortems, service pages, team pages, the deploy log and active alerts; read_doc(path).
If the evidence does not single out one cause, say so (root_cause null).
Reply with ONLY JSON: {"root_cause": "<service or null>", "confidence": "high|medium|low", "top3": ["svc","svc","svc"], "deploy_id": "<id or null>", "cites": ["doc/path.md", ...]}"""

TOOLS = [
    dict(name="search_docs", description="Keyword search over the company docs. Returns paths with snippets.",
         input_schema={"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}),
    dict(name="read_doc", description="Read one document by path.",
         input_schema={"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}),
]


def run_docs_agent(world, outcome, now, client=None, lead_model=None, max_steps=12):
    client = client or client_from_env()
    model = lead_model or model_for("lead", client.provider)       # same model as the graph Lead, so only the tools differ
    store = DocStore(render_docs(world, outcome, now))
    alerting = outcome.alerting

    def execute(name, args):
        if name == "search_docs":
            return json.dumps(store.search_docs(args["query"]))
        if name == "read_doc":
            return store.read_doc(args["path"])
        raise ValueError(f"unknown tool {name}")

    t0 = time.time()
    text, usage, _ = run_tool_loop(client, model, SYSTEM, f"{len(alerting)} services alerting: {', '.join(alerting)}. Deploy and alert history are in the docs.",
                                   TOOLS, execute, max_steps=max_steps, max_output_tokens=4000)
    m = re.search(r"\{.*\}", text or "", re.S)
    try:
        out = json.loads(m.group(0)) if m else {}
    except ValueError:
        out = {}
    cites = [c for c in out.get("cites", []) if isinstance(c, str)]
    ok = sum(1 for c in cites if c in store.seen)
    rc = out.get("root_cause")
    rc = rc if isinstance(rc, str) and rc.lower() not in ("null", "none", "undetermined") else "undetermined"
    top3 = [x for x in out.get("top3", []) if isinstance(x, str)] or ([rc] if rc != "undetermined" else [])
    conf = out.get("confidence") if out.get("confidence") in ("high", "medium", "low") else "low"
    return dict(root_cause=rc, confidence=conf, hypotheses=[dict(service=s) for s in top3], blames_deploy=out.get("deploy_id"),
                claims=dict(verified=ok, rejected=len(cites) - ok), duration_s=round(time.time() - t0, 3),
                tokens=usage["input"] + usage["output"], usage=usage,
                cost_usd=round((usage["input"] * 2.0 + usage["output"] * 10.0) / 1e6, 5))
