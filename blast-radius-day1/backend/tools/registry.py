"""One registry of read tools: name -> function + JSON schema. Agents and the MCP server will both use this."""
from backend.tools import read
from backend.tools.ranking import rank_root_causes

_S = {"type": "string"}
_SL = {"type": "array", "items": _S, "minItems": 1}

TOOLS = {
    "rank_root_causes": dict(fn=rank_root_causes, description="Rank which service best explains an alert storm (coverage x precision F1 over sync dependency paths).",
        schema=dict(type="object", properties=dict(alerting=_SL, top_k={"type": "integer", "default": 5}), required=["alerting"])),
    "blast_radius": dict(fn=read.blast_radius, description="What breaks if a service fails: failing now (sync) vs at risk (async), features, customers, ARR.",
        schema=dict(type="object", properties=dict(service=_S), required=["service"])),
    "dependencies": dict(fn=read.dependencies, description="What a service relies on, with hop counts.",
        schema=dict(type="object", properties=dict(service=_S, kind={"enum": ["sync", "async"]}, max_hops={"type": "integer", "default": 6}), required=["service"])),
    "recent_changes": dict(fn=read.recent_changes, description="Deploys to these services and their sync dependencies in the window before a timestamp.",
        schema=dict(type="object", properties=dict(services=_SL, until_ts={"type": "integer"}, window_minutes={"type": "integer", "default": 120}, hops={"type": "integer", "default": 2}), required=["services", "until_ts"])),
    "change_details": dict(fn=read.change_details, description="Diff summary, author and commits of one deploy.",
        schema=dict(type="object", properties=dict(deploy_id=_S), required=["deploy_id"])),
    "find_experts": dict(fn=read.find_experts, description="Who to page for a service, timezone-aware (who is awake at at_time).",
        schema=dict(type="object", properties=dict(service=_S, at_time={"type": "integer"}), required=["service"])),
    "similar_incidents": dict(fn=read.similar_incidents, description="Past incidents on this service or its neighborhood, plus what fixed them.",
        schema=dict(type="object", properties=dict(service=_S, text=_S, limit={"type": "integer", "default": 5}), required=["service"])),
    "lessons_for": dict(fn=read.lessons_for, description="Learned patterns and fixes (procedural memory) for a service and its dependencies.",
        schema=dict(type="object", properties=dict(service=_S), required=["service"])),
    "critical_services": dict(fn=read.critical_services, description="Chokepoints (betweenness) and most depended-on services (PageRank).",
        schema=dict(type="object", properties=dict(limit={"type": "integer", "default": 5}))),
    "path_between": dict(fn=read.path_between, description="Shortest dependency path between two services.",
        schema=dict(type="object", properties=dict(a=_S, b=_S, max_hops={"type": "integer", "default": 8}), required=["a", "b"])),
    "explore_graph": dict(fn=read.explore_graph, description="Read-only Cypher escape hatch (GRAPH.RO_QUERY, row limit, timeout).",
        schema=dict(type="object", properties=dict(cypher=_S, limit={"type": "integer", "default": 100}), required=["cypher"])),
}


def tool_specs():
    """Anthropic/MCP-style tool definitions."""
    return [dict(name=n, description=t["description"], input_schema=t["schema"]) for n, t in TOOLS.items()]


def call_tool(graph, name, args=None):
    if name not in TOOLS:
        raise KeyError(f"unknown tool: {name}")
    args = dict(args or {})
    schema = TOOLS[name]["schema"]
    missing = [k for k in schema.get("required", []) if k not in args]
    if missing:
        raise ValueError(f"{name}: missing argument(s): {', '.join(missing)}")
    extra = [k for k in args if k not in schema["properties"]]
    if extra:
        raise ValueError(f"{name}: unexpected argument(s): {', '.join(extra)}")
    return TOOLS[name]["fn"](graph, **args)
