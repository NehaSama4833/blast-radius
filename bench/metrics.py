"""Scoring. One result per scenario; aggregate per tier and overall. No numbers are invented here: everything comes from runs."""
from collections import defaultdict


def score_one(spec, truth, result):
    """`result` needs: root_cause (str|'undetermined'), confidence, hypotheses (list of {service}), blames_deploy,
    claims {verified, rejected}, duration_s, tokens (int)."""
    roots = set(truth["root_causes"])
    multi = bool(truth.get("multiple_causes"))
    rc = result["root_cause"]
    abstained = rc in (None, "undetermined")
    top3 = {h["service"] for h in result.get("hypotheses", [])[:3]}
    return dict(
        id=spec["id"], tier=spec["tier"], world=spec["world"], expected=sorted(roots), answered=rc, confidence=result["confidence"],
        top1=(not abstained and rc in roots) if not multi else False,
        top3=bool(roots & top3) if not multi else bool(roots <= top3),
        deploy_found=(result.get("blames_deploy") in truth["deploy_ids"]) if not multi else False,
        abstained=abstained,
        correct_abstention=(abstained and multi),
        wrong_abstention=(abstained and not multi),
        confident_and_wrong=(not abstained and not multi and rc not in roots) or (not abstained and multi),
        invalid_citations=result["claims"]["rejected"], claims=result["claims"]["verified"] + result["claims"]["rejected"],
        duration_s=result["duration_s"], tokens=result.get("tokens", 0))


def _rate(rows, key):
    return round(sum(1 for r in rows if r[key]) / len(rows), 3) if rows else None


def aggregate(scored):
    out = {}
    groups = defaultdict(list)
    for r in scored:
        groups["all"].append(r)
        groups[r["tier"]].append(r)
    for g, rows in groups.items():
        single = [r for r in rows if r["tier"] != "ambiguous"]
        amb = [r for r in rows if r["tier"] == "ambiguous"]
        out[g] = dict(n=len(rows), top1=_rate(single, "top1"), top3=_rate(single, "top3"), deploy_found=_rate(single, "deploy_found"),
                      wrong_abstentions=sum(r["wrong_abstention"] for r in single), n_single=len(single),
                      correct_abstentions=f"{sum(r['correct_abstention'] for r in amb)}/{len(amb)}" if amb else None,
                      invalid_citations=sum(r["invalid_citations"] for r in rows), claims=sum(r["claims"] for r in rows),
                      mean_duration_s=round(sum(r["duration_s"] for r in rows) / len(rows), 2), tokens=sum(r["tokens"] for r in rows))
    # calibration: are 'high' verdicts right more often than 'medium'/'low'?
    cal = {}
    for lvl in ("high", "medium", "low"):
        rows = [r for r in scored if r["confidence"] == lvl and not r["abstained"] and r["tier"] != "ambiguous"]
        cal[lvl] = dict(n=len(rows), correct=round(sum(r["top1"] for r in rows) / len(rows), 3) if rows else None)
    out["calibration"] = cal
    return out
