"""Root-cause ranking (design doc section 4).

Cypher finds who can reach whom; THIS file does the scoring, in plain Python, so it is easy to test.

For a candidate c:
  explains(c) = alerting services with a sync path to c (c itself counts if it is alerting),
                plus alerting services with a direct ASYNC edge to c (lag alerts, see ARCHITECTURE.md)
  predicts(c) = the MONITORED services among {c} + everything that should break if c broke
  coverage    = |explains| / |alerting|        precision = |explains| / |predicts|
  score       = F1(coverage, precision)
Ties go to a silent (monitored:false) candidate, then to the one deeper in the stack.
"""
from backend.tools.base import ToolResult, cite, require_services, rows

LAYER_DEPTH = {"edge": 0, "api": 1, "core": 2, "data": 3}
MULTI_CAUSE_THRESHOLD = 0.7   # design doc: "no candidate explains at least 70% of alerts"
WEAK_FIT_THRESHOLD = 0.7


def f1(a: float, b: float) -> float:
    return 0.0 if a + b == 0 else 2 * a * b / (a + b)


def score_candidates(alerting, explains, predicts, meta, mode="f1"):
    """Pure function. alerting: set[str]; explains/predicts: {candidate: set[str]};
    meta: {candidate: {"monitored": bool, "layer": str}}. Returns a sorted list of dicts."""
    alerting = set(alerting)
    out = []
    for c, ex in explains.items():
        ex = set(ex) & alerting
        pr = set(predicts.get(c, set()))
        coverage = len(ex) / len(alerting) if alerting else 0.0
        precision = len(ex) / len(pr) if pr else 0.0
        out.append(dict(
            candidate=c, monitored=meta[c]["monitored"], layer=meta[c]["layer"],
            explains=sorted(ex), predicts=sorted(pr),
            unexplained=sorted(alerting - ex),
            predicted_not_alerting=sorted(pr - alerting),
            coverage=round(coverage, 4), precision=round(precision, 4),
            score=round(coverage if mode == "coverage" else f1(coverage, precision), 4)))
    out.sort(key=lambda r: (-r["score"], r["monitored"], -LAYER_DEPTH[r["layer"]], r["candidate"]))
    for i, r in enumerate(out, start=1):
        r["rank"] = i
    return out


def split_causes(alerting, explains, predicts, meta, max_causes=2, min_precision=0.7, min_joint_coverage=0.85):
    """Greedy cover for storms with more than one cause. Take the best candidate, remove the alerts it explains, then rank the
    leftover alerts on their own. Accept the set only if every pick is precise (at least 70% of what it predicts is really alerting), explains 2+ alerts, and together they explain
    at least 85% of the alerts. Returns [] when no clean split exists."""
    alerting = set(alerting)
    left, picks = set(alerting), []
    for _ in range(max_causes):
        done = alerting - left                      # alerts already accounted for: do not count them against the next candidate
        ranked = score_candidates(left, {c: set(e) & left for c, e in explains.items() if set(e) & left},
                                  {c: set(p) - done for c, p in predicts.items()}, meta)
        if not ranked or ranked[0]["precision"] < min_precision or len(ranked[0]["explains"]) < 2:
            return []
        top = ranked[0]
        picks.append(dict(candidate=top["candidate"], explains=top["explains"], score=top["score"], monitored=top["monitored"]))
        left -= set(top["explains"])
        if not left:
            break
    covered = len(alerting) - len(left)
    return picks if len(picks) > 1 and covered / len(alerting) >= min_joint_coverage else []


def describe(r, n_alerting):
    ex, pr = len(r["explains"]), len(r["predicts"])
    s = f"{r['candidate']} explains {ex} of {n_alerting} alerts. If it failed, {pr} monitored service{'s' if pr != 1 else ''} should alert; {ex} do"
    gone = r["predicted_not_alerting"]
    if gone:
        s += f" (not alerting: {', '.join(gone)})"
    s += "."
    if r["unexplained"]:
        s += f" It does not explain: {', '.join(r['unexplained'])}."
    if not r["monitored"]:
        s += f" {r['candidate']} has no monitoring, so it would fail silently."
    return s


def rank_root_causes(graph, alerting, top_k=5, mode="f1") -> ToolResult:
    alerting = sorted(set(alerting))
    if not alerting:
        raise ValueError("alerting must list at least one service")
    require_services(graph, alerting)

    expl = rows(graph, """
        UNWIND $alerting AS name
        MATCH (a:Service {name: name})-[:DEPENDS_ON*0..6 {kind: 'sync'}]->(c:Service)
        RETURN c.name AS candidate, collect(DISTINCT a.name) AS explains""", {"alerting": alerting})
    explains = {c: set(ex) for c, ex in expl}
    for c, ex in rows(graph, """
        UNWIND $alerting AS name
        MATCH (a:Service {name: name})-[:DEPENDS_ON {kind: 'async'}]->(c:Service)
        RETURN c.name, collect(DISTINCT a.name)""", {"alerting": alerting}):
        explains.setdefault(c, set()).update(ex)

    cands = sorted(explains)
    meta = {n: dict(monitored=m, layer=l) for n, m, l in rows(
        graph, "UNWIND $c AS x MATCH (s:Service {name:x}) RETURN s.name, s.monitored, s.layer", {"c": cands})}

    def fetch_predicts(batch):
        out = {c: ({c} if meta[c]["monitored"] else set()) for c in batch}
        for c, us in rows(graph, """
            UNWIND $c AS cname
            MATCH (u:Service {monitored: true})-[:DEPENDS_ON*1..6 {kind: 'sync'}]->(c:Service {name: cname})
            RETURN cname, collect(DISTINCT u.name)""", {"c": batch}):
            out[c] |= set(us)
        for c, us in rows(graph, """
            UNWIND $c AS cname
            MATCH (u:Service {monitored: true})-[:DEPENDS_ON {kind: 'async'}]->(c:Service {name: cname})
            RETURN cname, collect(DISTINCT u.name)""", {"c": batch}):
            out[c] |= set(us)
        return out

    # Exact branch-and-bound: precision <= 1, so a candidate's score can never beat F1(coverage, 1) = 2c/(1+c)
    # (or c itself in coverage mode). Visit candidates by coverage, stop once that bound falls strictly below the
    # k-th best score found so far. Same top-k as scoring everyone, far fewer expensive blast-radius walks on big graphs.
    n_alert = len(alerting)
    cov = {c: len(explains[c] & set(alerting)) / n_alert for c in cands}
    bound = (lambda c: cov[c]) if mode == "coverage" else (lambda c: 2 * cov[c] / (1 + cov[c]) if cov[c] else 0.0)
    order = sorted(cands, key=lambda c: -cov[c])
    k = max(top_k, 5)
    predicts, scored = {}, []
    for i in range(0, len(order), 25):
        batch = order[i:i + 25]
        if len(scored) >= k and bound(batch[0]) < sorted(scored, reverse=True)[k - 1]:
            break
        predicts.update(fetch_predicts(batch))
        scored = [r["score"] for r in score_candidates(alerting, {c: explains[c] for c in predicts}, predicts, meta, mode)]
    pruned = len(cands) - len(predicts)
    explains_all = explains
    explains = {c: explains_all[c] for c in predicts}

    ranked = score_candidates(alerting, explains, predicts, meta, mode)
    for r in ranked:
        r["summary"] = describe(r, len(alerting))
    best_cov = max(r["coverage"] for r in ranked)
    best_cov = max(cov.values())
    if best_cov < MULTI_CAUSE_THRESHOLD or ranked[0]["score"] < WEAK_FIT_THRESHOLD:
        rest = [c for c in cands if c not in predicts]                  # the split needs everyone: fetch the rest
        for i in range(0, len(rest), 50):
            predicts.update(fetch_predicts(rest[i:i + 50]))
        cause_set = split_causes(alerting, explains_all, predicts, meta)
    else:
        cause_set = []
    top = ranked[:top_k]
    data = dict(
        alerting=alerting, n_alerting=len(alerting), n_candidates=len(cands), n_scored=len(ranked), candidates=top, cause_set=cause_set,
        likely_multiple_causes=best_cov < MULTI_CAUSE_THRESHOLD,
        weak_fit=ranked[0]["score"] < WEAK_FIT_THRESHOLD,
        note=("No single service explains at least 70% of the alerts: likely more than one cause."
              if best_cov < MULTI_CAUSE_THRESHOLD else None))
    cites = [cite("Service", a) for a in alerting] + [cite("Service", r["candidate"]) for r in top]
    return ToolResult(data, cites, {"tool": "rank_root_causes", "params": {"alerting": alerting, "top_k": top_k}})
