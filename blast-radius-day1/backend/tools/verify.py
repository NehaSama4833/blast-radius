"""verify_mitigation: "would this fix clear every alert?" -- checked on a COPY of the graph.

This is a SIMULATION against the dependency graph (labelled that way in the UI). The real confirmation in
production is watching the alerts clear.
"""
import uuid

from backend.graph.db import copy_graph, drop_graph
from backend.tools.base import ToolResult, cite, require_services, rows
from backend.world import failure

DRAIN_MINUTES = 10                     # assumed time for async lag to drain after the fix
ACTIONS = ("rollback", "restart", "scale", "hotfix", "config")


def world_from_graph(graph):
    services = [dict(name=n, monitored=m, layer=l) for n, m, l in rows(graph, "MATCH (s:Service) RETURN s.name, s.monitored, s.layer")]
    deps = [dict(src=a, dst=b, kind=k) for a, b, k in rows(graph, "MATCH (a:Service)-[r:DEPENDS_ON]->(b:Service) RETURN a.name, b.name, r.kind")]
    return dict(services=services, deps=deps)


def verify_mitigation(graph, action: str, service: str, current_alerting, deploy_id=None) -> ToolResult:
    """Pretend `action` fixes `service`; report which of `current_alerting` would clear and which would remain."""
    if action not in ACTIONS:
        raise ValueError(f"unknown action {action!r}; expected one of {ACTIONS}")
    require_services(graph, [service] + list(current_alerting))
    current = sorted(set(current_alerting))
    if action == "rollback":
        if not deploy_id:
            raise ValueError("rollback needs deploy_id")
        ok = rows(graph, "MATCH (d:Deploy {id:$id})-[:TO]->(s:Service {name:$s}) RETURN count(d)", {"id": deploy_id, "s": service})[0][0]
        if not ok:
            raise ValueError(f"{deploy_id} is not a deploy to {service}")

    scratch = f"sim_{uuid.uuid4().hex[:8]}"
    cp = copy_graph(graph.name, scratch)
    try:
        # apply the fix in the copy (the original is never touched)
        if deploy_id:
            cp.query("MATCH (d:Deploy {id:$id}) SET d.rolled_back = true", {"id": deploy_id})
        cp.query("MATCH (s:Service {name:$s}) SET s.healthy = true", {"s": service})
        world = world_from_graph(cp)
        caused_by_it = failure.alerting_for(world, [service])   # alerts this one fault explains
    finally:
        drop_graph(scratch)

    cleared = sorted(a for a in current if a in caused_by_it)
    lag = sorted(a for a in cleared if caused_by_it[a] == "lag")
    remaining = sorted(a for a in current if a not in caused_by_it)
    data = dict(action=action, service=service, deploy_id=deploy_id, simulated=True,
                cleared=cleared, remaining=remaining, all_clear=not remaining,
                lag_draining=lag, drain_minutes=DRAIN_MINUTES if lag else 0,
                summary=(f"{action} on {service} clears {len(cleared)} of {len(current)} alerts"
                         + (f"; {', '.join(lag)} need about {DRAIN_MINUTES} min to drain" if lag else "")
                         + (f"; still unexplained: {', '.join(remaining)}" if remaining else "")
                         + ". (Simulation against the dependency graph.)"))
    cites = [cite("Service", service)] + [cite("Service", a) for a in current] + ([cite("Deploy", deploy_id)] if deploy_id else [])
    return ToolResult(data, cites, {"tool": "verify_mitigation", "params": dict(action=action, service=service, deploy_id=deploy_id, current_alerting=current)})
