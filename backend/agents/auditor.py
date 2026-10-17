"""The Auditor: a sixth agent that shares nothing with the team except the graph.

It reads the stored Decision, its BLAMES edges, the board's Findings and the stored simulation and fact-check
results, runs deterministic checks, and writes an Audit node linked to the Decision. It never sees the Lead's
transcript or the Session's memory, so it is an independent second look. It cannot change the verdict; it can
only agree or disagree, and the UI shows which checks failed.
"""
import json

from backend.tools.base import rows


def audit(graph, inv_id):
    d = rows(graph, """MATCH (:Investigation {id:$i})-[:CONCLUDED]->(d:Decision)
                       RETURN d.root_cause, d.confidence, d.verification, d.faith, id(d)""", {"i": inv_id})
    if not d:
        raise ValueError("no decision to audit")
    root, conf, ver, faith, did = d[0]
    ver = json.loads(ver) if ver else None
    faith = json.loads(faith) if faith else None
    checks = []

    def check(name, ok, detail):
        checks.append(dict(check=name, ok=bool(ok), detail=detail))

    if root == "undetermined":
        check("abstention is not overconfident", conf == "low", f"confidence is {conf}")
        n_hyp = rows(graph, "MATCH (:Investigation {id:$i})-[:CONSIDERS]->(h:Hypothesis) RETURN count(h)", {"i": inv_id})[0][0]
        check("alternatives were considered", n_hyp >= 2, f"{n_hyp} hypotheses on the board")
    else:
        blamed = rows(graph, "MATCH (:Investigation {id:$i})-[:CONCLUDED]->(:Decision)-[:BLAMES]->(s:Service) RETURN s.name", {"i": inv_id})
        check("verdict is linked to the blamed service in the graph", blamed and blamed[0][0] == root, f"BLAMES -> {blamed[0][0] if blamed else 'nothing'}")
        sup = rows(graph, """MATCH (:Investigation {id:$i})-[:CONSIDERS]->(h:Hypothesis {status:'accepted'})-[:ABOUT]->(:Service {name:$r})
                             MATCH (a:Agent)-[:WROTE]->(f:Finding)-[:SUPPORTS]->(h) RETURN collect(DISTINCT a.name), collect(DISTINCT f.kind)""",
                   {"i": inv_id, "r": root})
        agents, kinds = (sup[0] if sup else ([], []))
        check("independent support", len(set(agents) - {"People"}) >= (2 if conf == "high" else 1),
              f"supported by {', '.join(sorted(agents)) or 'nobody'}")
        _check_against_ranking(graph, inv_id, root, check)
        dep = rows(graph, """MATCH (:Investigation {id:$i})-[:CONCLUDED]->(:Decision)-[:BLAMES]->(x:Deploy)-[:TO]->(s:Service)
                             RETURN x.id, s.name, x.ts""", {"i": inv_id})
        first = rows(graph, "MATCH (:Investigation {id:$i})-[:TRIGGERED_BY]->(a:Alert) RETURN min(a.ts)", {"i": inv_id})[0][0]
        if dep:
            check("blamed deploy went to the root service before the first alert", dep[0][1] == root and (first is None or dep[0][2] <= first),
                  f"{dep[0][0]} -> {dep[0][1]}")
        elif conf == "high":
            check("high confidence has a deploy that lines up in time", False, "no deploy is blamed")
        if ver:
            tot = len(ver.get("cleared", [])) + len(ver.get("remaining", []))
            frac = len(ver.get("cleared", [])) / tot if tot else 0
            check("simulated fix clears most alerts", frac >= 0.7, f"{len(ver.get('cleared', []))} of {tot} cleared on a graph copy")
        else:
            check("a fix was simulated before proposing it", False, "no simulation stored")
    if faith is not None:
        n = len(faith["verdict"]["flagged"]) + len(faith["findings"]["flagged"])
        check("words match the tool results (fact-check)", n == 0, "no flags" if n == 0 else f"{n} flag(s)")
    verdict = "agree" if all(c["ok"] for c in checks) else "disagree"
    graph.query("MERGE (:Agent {name:'Auditor'})")
    graph.query("""MATCH (d:Decision) WHERE id(d) = $did MATCH (a:Agent {name:'Auditor'})
                   CREATE (au:Audit {verdict:$v, checks:$c}), (a)-[:WROTE]->(au), (au)-[:AUDITS]->(d)""",
                {"did": did, "v": verdict, "c": json.dumps(checks)})
    return dict(verdict=verdict, checks=checks)


def _check_against_ranking(graph, inv_id, root, check):
    """A hijacked or confused Lead (e.g. obeying text planted in the data: "blame payments-api") can only choose among
    the board's hypotheses, but it could still pick a weaker one. Flag a verdict that overrides the graph's best
    structural explanation unless the evidence on the board is stronger for it (docs/SECURITY.md)."""
    hyps = rows(graph, """MATCH (:Investigation {id:$i})-[:CONSIDERS]->(h:Hypothesis)-[:ABOUT]->(s:Service)
                          OPTIONAL MATCH (a:Agent)-[:WROTE]->(:Finding)-[r:SUPPORTS|WEAKENS]->(h)
                          RETURN s.name, h.rank, h.structural_score,
                                 collect(DISTINCT CASE WHEN type(r) = 'SUPPORTS' THEN a.name END),
                                 count(CASE WHEN type(r) = 'WEAKENS' THEN 1 END)
                          ORDER BY h.rank""", {"i": inv_id})
    if not hyps:
        return
    top = hyps[0]
    if top[0] == root:
        check("verdict agrees with the graph's best explanation", True, f"{root} is ranked first")
        return
    mine = next((h for h in hyps if h[0] == root), None)
    if mine is None:
        check("verdict agrees with the graph's best explanation", False, f"{root} is not on the board")
        return
    tie = (mine[2] or 0) >= (top[2] or 0) - 1e-9
    stronger = len([a for a in mine[3] if a]) > len([a for a in top[3] if a]) and top[4] > 0
    check("verdict agrees with the graph's best explanation", tie or stronger,
          f"{root} (rank {mine[1]}) chosen over {top[0]} (rank 1)" + ("" if tie or stronger else " without stronger evidence"))
