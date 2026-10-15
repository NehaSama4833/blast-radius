"""The shared board: how agents coordinate THROUGH THE GRAPH.

An `Investigation` owns Hypothesis and Finding nodes. Agents never see each other's transcripts; the Lead reads
`read_board()`, which is a graph query. All writes go through this class, which enforces (in code, not in a prompt):
  * agent scoping: each agent may only call its own tools and write its own kind of finding, on this investigation;
  * citation check: a finding/decision may only cite node ids that one of this investigation's tool calls returned;
  * receipts: every Finding/Decision stores the tool calls (tool + parameters) and the graph version it came from.
"""
import json
import threading
import time
from dataclasses import dataclass, field

from backend.tools.registry import TOOLS, call_tool
from backend.tools.verify import verify_mitigation

AGENTS = ("Lead", "Impact", "Changes", "History", "People")

AGENT_TOOLS = {
    "Lead": {"rank_root_causes", "verify_mitigation"},
    "Impact": {"blast_radius", "critical_services", "dependencies"},
    "Changes": {"recent_changes", "change_details"},
    "History": {"similar_incidents", "lessons_for"},
    "People": {"find_experts"},
}
FINDING_KIND = {"Lead": "structural", "Impact": "impact", "Changes": "temporal", "History": "historical", "People": "people"}
CONFIDENCE = ("high", "medium", "low")

# node label -> the property that identifies it (ids look like "Deploy:d-482")
KEY_PROP = {"Service": "name", "Deploy": "id", "Incident": "id", "Person": "handle", "Team": "name", "Feature": "name",
            "Customer": "name", "Lesson": "pattern", "Commit": "sha", "Alert": "id"}


class BoardError(ValueError):
    pass


class CitationError(BoardError):
    def __init__(self, bad):
        self.bad = sorted(bad)
        super().__init__(f"cites node(s) this agent never saw in a tool result: {', '.join(self.bad)}")


@dataclass
class Session:
    graph: object
    inv_id: str
    alerting: list
    seen: dict = field(default_factory=lambda: {a: set() for a in AGENTS})   # ids each agent has been shown
    calls: dict = field(default_factory=lambda: {a: [] for a in AGENTS})     # receipts per agent
    claims_ok: int = 0
    claims_rejected: int = 0
    proposed: list = field(default_factory=list)
    _n: int = 0
    _lock: object = field(default_factory=threading.Lock, repr=False)
    listener: object = field(default=None, repr=False)     # optional fn(agent, tool, params, cites): lets the UI light up what each agent reads

    # ---- reading ---------------------------------------------------------------------------------------------
    def call(self, agent, tool, args=None):
        self._agent(agent)
        if tool not in AGENT_TOOLS[agent]:
            raise BoardError(f"{agent} may not call {tool}")
        if tool == "verify_mitigation":
            res = verify_mitigation(self.graph, **(args or {}))
        else:
            res = call_tool(self.graph, tool, args)
        with self._lock:
            self.seen[agent].update(res.cites)
            self.calls[agent].append(dict(res.receipt, cites=sorted(set(res.cites))))
        if self.listener:
            try:
                self.listener(agent, tool, res.receipt.get("params", {}), sorted(set(res.cites)))
            except Exception:
                pass                                         # a UI hook must never break an investigation
        return res

    # ---- writing ---------------------------------------------------------------------------------------------
    def create_hypotheses(self, ranked):
        """Lead writes the top candidates (from rank_root_causes) onto the board."""
        rows = [dict(id=f"h-{self.inv_id}-{c['rank']}", rank=c["rank"], score=c["score"], service=c["candidate"]) for c in ranked]
        self.graph.query("""UNWIND $rows AS r MATCH (i:Investigation {id:$inv}), (s:Service {name:r.service})
                            CREATE (h:Hypothesis {id:r.id, rank:r.rank, structural_score:r.score, status:'open'}),
                                   (i)-[:CONSIDERS]->(h), (h)-[:ABOUT]->(s)""", {"rows": rows, "inv": self.inv_id})
        return [r["id"] for r in rows]

    def add_finding(self, agent, hypothesis_id, text, supports, cites, weight=1.0):
        self._agent(agent)
        kind = FINDING_KIND[agent]
        if not self.graph.query("MATCH (:Investigation {id:$i})-[:CONSIDERS]->(h:Hypothesis {id:$h}) RETURN count(h)",
                                {"i": self.inv_id, "h": hypothesis_id}).result_set[0][0]:
            raise BoardError(f"{hypothesis_id} is not a hypothesis of {self.inv_id}")
        with self._lock:
            self._check_cites(agent, cites)
            self._n += 1
            fid = f"f-{self.inv_id}-{self._n}"
        edge = "SUPPORTS" if supports else "WEAKENS"
        self.graph.query(f"""MATCH (h:Hypothesis {{id:$h}}), (a:Agent {{name:$agent}})
                             CREATE (f:Finding {{id:$fid, kind:$kind, text:$text, weight:$w, receipt:$receipt}}),
                                    (a)-[:WROTE]->(f), (f)-[:{edge}]->(h)""",
                         dict(h=hypothesis_id, agent=agent, fid=fid, kind=kind, text=text, w=float(weight),
                              receipt=self._receipt(agent, cites)))
        self._link_cites(fid, cites)
        return fid

    def propose_action(self, agent, action, service, deploy_id, rationale, cites):
        if agent != "Lead":
            raise BoardError("only the Lead proposes actions")
        self._check_cites(agent, cites)
        self.proposed.append(dict(action=action, service=service, deploy_id=deploy_id, rationale=rationale, cites=sorted(set(cites))))

    def record_decision(self, root_cause, confidence, reasons, cites, blames_deploy=None):
        """Lead's verdict. root_cause=None means 'cannot tell' (abstain); `reasons` must be non-empty either way."""
        if confidence not in CONFIDENCE:
            raise BoardError(f"confidence must be one of {CONFIDENCE}")
        if not reasons:
            raise BoardError("a decision needs reasons")
        self._check_cites("Lead", cites)
        if root_cause is None and confidence == "high":
            raise BoardError("an abstention cannot be high confidence")
        # a re-decision (Ripple) keeps the old verdict for the audit trail but moves it off the live CONCLUDED edge
        self.graph.query("MATCH (i:Investigation {id:$i})-[r:CONCLUDED]->(d:Decision) CREATE (i)-[:PREVIOUSLY_CONCLUDED]->(d) DELETE r", {"i": self.inv_id})
        self.graph.query("""MATCH (i:Investigation {id:$i})
                            CREATE (d:Decision {root_cause:$rc, confidence:$c, reasons:$r, actions:$a, receipt:$rec}),
                                   (i)-[:CONCLUDED]->(d)""",
                         dict(i=self.inv_id, rc=root_cause or "undetermined", c=confidence, r=json.dumps(reasons),
                              a=json.dumps(self.proposed), rec=self._receipt("Lead", cites)))
        if root_cause:
            self.graph.query("MATCH (:Investigation {id:$i})-[:CONCLUDED]->(d:Decision), (s:Service {name:$s}) CREATE (d)-[:BLAMES]->(s)",
                             {"i": self.inv_id, "s": root_cause})
        if blames_deploy:
            self.graph.query("MATCH (:Investigation {id:$i})-[:CONCLUDED]->(d:Decision), (x:Deploy {id:$x}) CREATE (d)-[:BLAMES]->(x)",
                             {"i": self.inv_id, "x": blames_deploy})
        if root_cause:
            self.graph.query("""MATCH (:Investigation {id:$i})-[:CONSIDERS]->(h:Hypothesis)-[:ABOUT]->(s:Service)
                                SET h.status = CASE WHEN s.name = $rc THEN 'accepted' ELSE 'rejected' END""", {"i": self.inv_id, "rc": root_cause})
        return dict(root_cause=root_cause or "undetermined", confidence=confidence, reasons=reasons)

    def supersede_findings(self, finding_ids):
        """Retire findings that a late alert made out of date. They stay in the graph (audit trail) but leave the live board."""
        if not finding_ids:
            return 0
        self.graph.query("""MATCH (f:Finding)-[r:SUPPORTS|WEAKENS]->(h:Hypothesis) WHERE f.id IN $ids
                            CREATE (f)-[:SUPERSEDED_FOR]->(h) SET f.was = type(r) DELETE r""", {"ids": sorted(finding_ids)})
        return len(finding_ids)

    # ---- reading the board (a graph query: the Lead's only view of the specialists) ----------------------------
    def read_board(self):
        rows = self.graph.query("""
            MATCH (:Investigation {id:$i})-[:CONSIDERS]->(h:Hypothesis)-[:ABOUT]->(s:Service)
            OPTIONAL MATCH (f:Finding)-[r:SUPPORTS|WEAKENS]->(h)
            OPTIONAL MATCH (a:Agent)-[:WROTE]->(f)
            RETURN h.id, h.rank, h.structural_score, h.status, s.name, f.id, f.kind, f.text, f.weight, type(r), a.name, f.receipt
            ORDER BY h.rank, f.id""", {"i": self.inv_id}).result_set
        board = {}
        for hid, rank, score, status, svc, fid, kind, text, w, rel, agent, receipt in rows:
            h = board.setdefault(hid, dict(hypothesis_id=hid, rank=rank, service=svc, structural_score=score, status=status, findings=[]))
            if fid:
                try:
                    rc = json.loads(receipt) if receipt else None
                except ValueError:
                    rc = None
                h["findings"].append(dict(id=fid, agent=agent, kind=kind, text=text, weight=w, effect=rel.lower(), receipt=rc))
        # Reading the board shows the Lead what the findings cite, so the Lead may cite those nodes too.
        cited = self.graph.query("""MATCH (:Investigation {id:$i})-[:CONSIDERS]->(:Hypothesis)<-[:SUPPORTS|WEAKENS]-(f:Finding)-[:CITES]->(n)
                                   RETURN labels(n)[0], n.name, n.id, n.handle, n.pattern, n.sha""", {"i": self.inv_id}).result_set
        with self._lock:
            for label, name, nid, handle, pattern, sha in cited:
                key = {"Service": name, "Team": name, "Feature": name, "Customer": name, "Deploy": nid, "Incident": nid, "Alert": nid,
                       "Person": handle, "Lesson": pattern, "Commit": sha}.get(label)
                if key is not None:
                    self.seen["Lead"].add(f"{label}:{key}")
        return sorted(board.values(), key=lambda h: h["rank"])

    def verification(self):
        return dict(verified=self.claims_ok, rejected=self.claims_rejected)

    # ---- internals -------------------------------------------------------------------------------------------
    def _agent(self, agent):
        if agent not in AGENTS:
            raise BoardError(f"unknown agent {agent!r}")

    def _check_cites(self, agent, cites):
        cites = set(cites)
        if not cites:
            self.claims_rejected += 1
            raise BoardError("every claim must cite at least one node")
        bad = {c for c in cites if c not in self.seen[agent] or c.split(":", 1)[0] not in KEY_PROP}
        if bad:
            self.claims_rejected += 1
            raise CitationError(bad)
        self.claims_ok += 1

    def _receipt(self, agent, cites):
        cites = set(cites)
        used = [c for c in self.calls[agent] if cites & set(c["cites"])]
        meta = self.graph.query("MATCH (m:Meta) RETURN m.world, m.loaded_at").result_set
        version = f"{meta[0][0]}@{meta[0][1]}" if meta else "unknown"
        return json.dumps(dict(graph_version=version, calls=[dict(tool=c["tool"], params=c["params"]) for c in used],
                               nodes_read=sorted(cites)), sort_keys=True)

    def _link_cites(self, finding_id, cites):
        for c in sorted(set(cites)):
            label, val = c.split(":", 1)          # label is checked against KEY_PROP, so it is safe to put in the query
            self.graph.query(f"MATCH (f:Finding {{id:$fid}}), (n:{label} {{{KEY_PROP[label]}:$v}}) CREATE (f)-[:CITES]->(n)",
                             {"fid": finding_id, "v": val})


def start_investigation(graph, alerting, model="stub", now=None):
    """Create the Investigation, the five Agent nodes, and link the triggering Alerts."""
    now = int(now if now is not None else time.time())
    n = graph.query("MATCH (i:Investigation) RETURN count(i)").result_set[0][0] + 1
    inv = f"inv-{n}"
    graph.query("CREATE (:Investigation {id:$id, ts:$ts, status:'open', model:$m, tokens:0, duration_ms:0})", {"id": inv, "ts": now, "m": model})
    for a in AGENTS:
        graph.query("MERGE (:Agent {name:$n})", {"n": a})
    graph.query("""MATCH (i:Investigation {id:$id}) UNWIND $alerting AS name
                   MATCH (a:Alert)-[:ON]->(:Service {name:name}) WHERE a.ts <= $now
                   MERGE (i)-[:TRIGGERED_BY]->(a)""", {"id": inv, "alerting": sorted(set(alerting)), "now": now})
    return Session(graph, inv, sorted(set(alerting)))
