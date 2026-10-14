"""Shared plumbing for tools: every tool returns a ToolResult carrying the data, the node ids it read
(`cites`, used later by the citation checker) and a receipt (tool + parameters)."""
from dataclasses import dataclass, field


@dataclass
class ToolResult:
    data: dict
    cites: list = field(default_factory=list)      # ids like "Service:ledger-db", "Deploy:d-482"
    receipt: dict = field(default_factory=dict)

    def as_dict(self):
        return {"data": self.data, "cites": sorted(set(self.cites)), "receipt": self.receipt}


def cite(label: str, key) -> str:
    return f"{label}:{key}"


def rows(graph, query, params=None):
    return graph.query(query, params or {}).result_set


class UnknownService(ValueError):
    pass


def require_services(graph, names):
    found = {r[0] for r in rows(graph, "UNWIND $n AS x MATCH (s:Service {name:x}) RETURN s.name", {"n": list(names)})}
    missing = sorted(set(names) - found)
    if missing:
        raise UnknownService(f"unknown service(s): {', '.join(missing)}")
