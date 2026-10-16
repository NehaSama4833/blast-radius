"""Ask the graph: a free-text question answered by one small model using ONLY the read-only graph tools.

Same honesty rules as the agents: the answer may only cite node ids that its own tool results contained;
anything else is dropped and counted. Short budget (few steps, few tokens). Read-only: the tools cannot write.
"""
import json
import re

from backend.agents.llm import model_for, run_tool_loop
from backend.tools.registry import call_tool, tool_specs

SYSTEM = """You answer questions about a company's systems using ONLY the provided graph tools (services, dependencies, deploys, incidents, people, features, customers).
Call tools to find facts; never guess. Keep the answer under 80 words, plain language.
Reply with ONLY JSON: {"answer": "...", "cites": ["Label:key", ...]} where cites are node ids exactly as they appear in the cite_ids of your tool results."""


def ask(graph, question, client, model=None, max_steps=5):
    question = " ".join(str(question).split())[:300]
    if len(question) < 3:
        raise ValueError("ask a question")
    from backend.agents.faithful import check, numbers_in
    seen, calls, nums = set(), [], set()

    def execute(name, args):
        res = call_tool(graph, name, args)
        seen.update(res.cites)
        nums.update(numbers_in(res.data))
        calls.append(dict(tool=name, params=args))
        return json.dumps(dict(data=res.data, cite_ids=sorted(set(res.cites))), default=str)[:6000]

    text, usage, steps = run_tool_loop(client, model or model_for("agent", client.provider), SYSTEM, question, tool_specs(), execute,
                                       max_steps=max_steps, max_output_tokens=2000)
    m = re.search(r"\{.*\}", text or "", re.S)
    try:
        out = json.loads(m.group(0)) if m else {}
    except ValueError:
        out = {}
    answer = str(out.get("answer") or "I could not answer that from the graph.")[:800]
    cites = [c for c in out.get("cites", []) if isinstance(c, str)]
    ok = [c for c in cites if c in seen]
    names = [r[0] for r in graph.query("MATCH (s:Service) RETURN s.name").result_set]
    faith = check(answer, seen, nums, names)
    return dict(answer=answer, cites=ok, faithfulness=faith, rejected=len(cites) - len(ok), calls=calls, steps=steps,
                services=sorted({c.split(":", 1)[1] for c in ok if c.startswith("Service:")}), tokens=usage["input"] + usage["output"])
