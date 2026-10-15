"""Claude-backed policy: same three-part interface as RulePolicy (impact/changes/history/people/decide).

How the model is kept honest:
  * each specialist only gets its own tools (the Session enforces that again server-side);
  * a specialist can only write a finding by citing ids its own tool results contained (Session.add_finding checks);
  * the model never writes numbers into the pipeline: impact/deploy/precedent/people annotations are read straight
    out of the tool results, not out of the model's text;
  * the Lead's verdict is clamped by hard rules: it must pick one of the top hypotheses or abstain, it must abstain
    when the structural ranking says "likely more than one cause", and "high" confidence needs a strong structural
    fit plus a change that lines up in time;
  * any failure (bad JSON, API error, budget used up) falls back to the rule policy for that step, and says so.
"""
import json
import re
import threading

from backend.agents.board import AGENT_TOOLS, BoardError, FINDING_KIND
from backend.agents.llm import LLMError, client_from_env, model_for, run_tool_loop
from backend.agents.runner import ABSTAIN_BELOW, STRONG_FIT, RulePolicy
from backend.tools.registry import tool_specs

MAX_TOOL_CHARS = 6000

ROLE = {
    "Impact": "You are the Impact analyst. For each hypothesis, find out what would break if that service failed (services, features, customers, revenue) and whether every current alert sits inside that blast radius. A hypothesis whose blast radius does NOT cover the alerts is weakened.",
    "Changes": "You are the Changes analyst. For each hypothesis, look for deploys or config changes shortly before the first alert, on the service itself or something it depends on. A direct change just before the alert supports the hypothesis; no change weakens it.",
    "History": "You are the History analyst. For each hypothesis, look for past incidents and lessons on that service with the same pattern. A matching precedent supports it; none means you have nothing to say for it (do not invent one).",
    "People": "You are the People analyst. For the TOP hypothesis only, find who should be paged: people who own it or fixed it before, and are awake now. Write one supporting finding naming them.",
}
RULES = """Rules:
- Use only your tools for facts. Every finding must cite node ids exactly as they appear in the 'cite_ids' list of your tool results (like "Service:ledger-db" or "Deploy:d-12"). A finding citing anything else is rejected.
- Be concise: one or two sentences per finding. Do not guess.
- When done, reply with ONLY a JSON object: {"findings":[{"hypothesis_id":"...","supports":true|false,"text":"...","cites":["Label:key",...]}]}"""


def _extract_json(text):
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        raise ValueError("no JSON in reply")
    return json.loads(m.group(0))


class LLMPolicy:
    name = "claude"

    def __init__(self, client=None, lead_model=None, agent_model=None, max_steps=8, max_output_tokens=3000):
        self.client = client or client_from_env()
        prov = self.client.provider
        self.lead_model = lead_model or model_for("lead", prov)
        self.agent_model = agent_model or model_for("agent", prov)
        self.max_steps, self.max_output_tokens = max_steps, max_output_tokens
        self.fallback = RulePolicy()
        self.usage = {"lead": {"input": 0, "output": 0, "cache_read": 0}, "agent": {"input": 0, "output": 0, "cache_read": 0}}
        self.notes = []                       # what fell back to rules, for the audit trail
        self._lock = threading.Lock()

    # ---- helpers ---------------------------------------------------------------------------------------------
    def _add_usage(self, role, u):
        with self._lock:
            for k in self.usage[role]:
                self.usage[role][k] += u.get(k, 0)

    def cost_usd(self, prices=None):
        """Default prices are USD per million tokens (input, output) from Anthropic's price page: Sonnet 5.5 and Haiku 5.5."""
        p = prices or {"lead": (2.0, 10.0), "agent": (0.10, 0.50)}
        return round(sum(self.usage[r]["input"] * p[r][0] + self.usage[r]["output"] * p[r][1] for r in p) / 1e6, 5)

    def _specialist(self, agent, s, hyps, ctx, emit, targets):
        names = AGENT_TOOLS[agent]
        tools = [t for t in tool_specs() if t["name"] in names]
        captured = []

        def execute(tool, args):
            res = s.call(agent, tool, args)
            captured.append((tool, dict(args), res.data))
            out = json.dumps(dict(data=res.data, cite_ids=sorted(set(res.cites))), default=str)
            return out[:MAX_TOOL_CHARS]

        hyp_text = "\n".join(f"- {h['id']}: service {h['service']} (structural fit {h['structural_score']}): {h['summary']}" for h in targets)
        user = (f"Alerting services now: {', '.join(ctx['alerting'])}.\nTime now (unix): {ctx['now']}. First alert (unix): {ctx['first_alert_ts']}.\n"
                f"Hypotheses to assess:\n{hyp_text}")
        try:
            text, usage, steps = run_tool_loop(self.client, self.agent_model, ROLE[agent] + "\n" + RULES, user, tools, execute,
                                               max_steps=self.max_steps, max_output_tokens=self.max_output_tokens)
            self._add_usage("agent", usage)
            out = _extract_json(text)
        except (LLMError, ValueError, BoardError, KeyError) as e:
            self.notes.append(f"{agent}: model step failed ({type(e).__name__}); used the rule policy")
            emit(agent, f"model step failed ({type(e).__name__}); falling back to rules", kind="notice")
            return False
        emit(agent, f"{steps} model step(s), {len(captured)} tool call(s)")
        ids = {h["id"] for h in targets}
        weight = 0.5 if agent == "People" else 1.0
        for f in out.get("findings", []):
            if f.get("hypothesis_id") not in ids or not str(f.get("text", "")).strip():
                continue
            try:
                s.add_finding(agent, f["hypothesis_id"], str(f["text"])[:600], bool(f.get("supports")), list(f.get("cites") or []), weight=weight)
                svc = next(h["service"] for h in targets if h["id"] == f["hypothesis_id"])
                emit(agent, ("supports " if f.get("supports") else "weakens ") + svc, kind="finding")
            except BoardError as e:               # includes CitationError: the claim is dropped, and counted as rejected
                emit(agent, f"claim rejected by the citation check: {str(e)[:120]}", kind="notice")
        self._annotate(agent, hyps, ctx, captured)
        return True

    @staticmethod
    def _annotate(agent, hyps, ctx, captured):
        """Facts for the verdict and the Discord draft come from tool results, never from model text."""
        by_svc = {h["service"]: h for h in hyps}
        for tool, args, data in captured:
            svc = args.get("service") or (args.get("services") or [None])[0]
            h = by_svc.get(svc)
            if not h:
                continue
            if tool == "blast_radius":
                h["impact"] = dict(arr=data["arr_at_risk"], features=data["features"], customers=len(data["customers"]), at_risk=data["at_risk_async"],
                                   failing=len(data["failing_now"]), by_plan=data["customers_by_plan"])
            elif tool == "recent_changes":
                own = [c for c in data["changes"] if c["service"] == svc]
                if own:
                    h["deploy"] = own[0]
            elif tool == "similar_incidents":
                same = [i for i in data["incidents"] if "same root-cause service" in i["why"]]
                if same:
                    h["_inc"] = same[0]
            elif tool == "lessons_for":
                h["_lessons"] = [l for l in data["lessons"] if l["about"] == svc]
            elif tool == "find_experts" and data["experts"]:
                pick = ([p for p in data["experts"] if p["awake"]] or data["experts"])[:2]
                h["people"] = dict(pick=[dict(name=p["name"], handle=p["handle"], awake=p["awake"], roles=p["roles"], local_time=p["local_time"]) for p in pick],
                                   channel=data["owner_channel"])
        for h in hyps:
            if h.get("_inc"):
                i, les = h["_inc"], h.get("_lessons") or []
                h["precedent"] = dict(incident=i["incident_id"], action=i["action"], ttr=i["ttr_min"], fix=(les[0]["fix"] if les else i["resolution"]),
                                      times_seen=(les[0]["times_seen"] if les else 1))

    # ---- specialists -----------------------------------------------------------------------------------------
    def impact(self, s, hyps, ctx, emit):
        if not self._specialist("Impact", s, hyps, ctx, emit, hyps):
            self.fallback.impact(s, hyps, ctx, emit)

    def changes(self, s, hyps, ctx, emit):
        if not self._specialist("Changes", s, hyps, ctx, emit, hyps):
            self.fallback.changes(s, hyps, ctx, emit)

    def history(self, s, hyps, ctx, emit):
        if not self._specialist("History", s, hyps, ctx, emit, hyps):
            self.fallback.history(s, hyps, ctx, emit)

    def people(self, s, hyps, ctx, emit):
        if not self._specialist("People", s, hyps, ctx, emit, hyps[:1]):
            self.fallback.people(s, hyps, ctx, emit)

    # ---- Lead ------------------------------------------------------------------------------------------------
    def decide(self, s, hyps, board, ctx, emit):
        d = self._decide(s, hyps, board, ctx, emit)
        seen = s.seen["Lead"]
        d["cites"] = [c for c in d["cites"] if c in seen] or [c for c in seen if c.startswith("Service:")][:1]     # the Lead may only cite what it has seen
        return d

    def _decide(self, s, hyps, board, ctx, emit):
        rule = self.fallback.decide(s, hyps, board, ctx, lambda *a, **k: None)     # also fills h['support_kinds']; used as the safety net
        rk = ctx["ranking"]
        top = rk["candidates"][0]
        if rk["likely_multiple_causes"] or rk["weak_fit"] or len(top["unexplained"]) >= 2:
            emit("Lead", "ranking says more than one cause is likely: abstaining (not up to the model)")
            return rule                                                             # structural abstention is a hard rule
        brief = [dict(id=b["hypothesis_id"], service=b["service"], structural_score=b["structural_score"],
                      findings=[dict(agent=f["agent"], effect=f["effect"], text=f["text"]) for f in b["findings"]]) for b in board]
        system = ("You are the Lead incident commander. Choose the most likely root cause from the hypotheses on the board, or say it is undetermined. "
                  "Use only the board. Reply with ONLY JSON: {\"root_cause\": \"<service or null>\", \"confidence\": \"high|medium|low\", \"reasons\": [\"...\"]} "
                  "with at most 3 short reasons. Be calibrated: if evidence is thin or conflicting, say low or null.")
        user = f"{len(ctx['alerting'])} services alerting: {', '.join(ctx['alerting'])}.\nBoard:\n{json.dumps(brief, default=str)}"
        try:
            rep = self.client.complete(self.lead_model, system, [{"role": "user", "text": user}], None, max_tokens=700, temperature=0.0)
            self._add_usage("lead", rep.usage)
            out = _extract_json(rep.text)
        except (LLMError, ValueError) as e:
            self.notes.append(f"Lead: model step failed ({type(e).__name__}); used the rule policy")
            emit("Lead", f"model step failed ({type(e).__name__}); falling back to rules", kind="notice")
            return rule
        pick = out.get("root_cause")
        best = next((h for h in hyps if h["service"] == pick), None)
        if pick is None or str(pick).lower() in ("null", "none", "undetermined"):
            return self._abstain(top, out.get("reasons"))
        if best is None:
            emit("Lead", f"model named {pick!r}, which is not on the board: using the rule verdict", kind="notice")
            return rule
        cand = next(c for c in rk["candidates"] if c["candidate"] == pick)
        kinds = {f["kind"] for f in next(b for b in board if b["hypothesis_id"] == best["id"])["findings"] if f["effect"] == "supports" and f["weight"] >= 0.5}
        conf = out.get("confidence") if out.get("confidence") in ("high", "medium", "low") else "low"
        if conf == "high" and not (cand["score"] >= STRONG_FIT and "temporal" in kinds and len(kinds) >= 2):
            conf = "medium"                                                         # cannot be 'high' without structure + a change in time + one more kind
        if conf == "medium" and not (cand["score"] >= ABSTAIN_BELOW and kinds):
            conf = "low"
        reasons = [str(r)[:300] for r in (out.get("reasons") or [])][:3] or rule["reasons"]
        reasons.insert(0, f"{pick} explains {len(cand['explains'])} of {ctx['n_alerting']} alerts and predicts {len(cand['predicts'])} services.")
        cites = [f"Service:{pick}"]
        if "temporal" in kinds and best.get("deploy"):
            cites.append(f"Deploy:{best['deploy']['deploy_id']}")
        if "historical" in kinds and best.get("precedent"):
            cites.append(f"Incident:{best['precedent']['incident']}")
        cites = [c for c in cites if c in s.seen["Lead"]] or [f"Service:{top['candidate']}"]
        return dict(root_cause=pick, confidence=conf, reasons=reasons, cites=cites,
                    blames_deploy=best["deploy"]["deploy_id"] if "temporal" in kinds and best.get("deploy") else None, best=best)

    @staticmethod
    def _abstain(top, reasons):
        rs = [str(r)[:300] for r in (reasons or [])][:3] or ["The evidence on the board does not single out one cause."]
        return dict(root_cause=None, confidence="low", reasons=rs, cites=[f"Service:{top['candidate']}"], blames_deploy=None, best=None)
