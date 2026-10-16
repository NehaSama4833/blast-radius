"""MCP server: the same read tools as the agents use, so Claude Desktop / Claude Code can investigate a graph.

Run (stdio):            python -m mcp_server.server
Run (streamable HTTP):  python -m mcp_server.server --http
Env: GRAPH_NAME (default "acme"), FALKORDB_URL (optional). If the graph is empty it is seeded from the world of that name.
Only READ tools are exposed. Writes (board, resolutions) stay inside the app, behind the server-side checks.
"""
import json
import os
import sys
import time

from mcp.server.mcpserver import MCPServer

from backend.graph.db import get_graph
from backend.tools.base import UnknownService
from backend.tools.registry import call_tool

GRAPH_NAME = os.environ.get("GRAPH_NAME", "acme")
_graph = None


def graph():
    """Lazily open the graph, seeding the demo world the first time."""
    global _graph
    if _graph is None:
        g = get_graph(GRAPH_NAME)
        if g.query("MATCH (s:Service) RETURN count(s)").result_set[0][0] == 0 and GRAPH_NAME == "pypi":
            from backend.world.pypi import load_pypi
            load_pypi(g)                                   # the real PyPI ecosystem (~30 s the first time)
        elif g.query("MATCH (s:Service) RETURN count(s)").result_set[0][0] == 0:
            from backend.world import get_world
            from backend.world.loader import load_world
            load_world(g, get_world(GRAPH_NAME.split("_")[0] if GRAPH_NAME.split("_")[0] in ("acme", "globex") else "acme"), now=time.time())
        _graph = g
    return _graph


def _run(name, **args):
    args = {k: v for k, v in args.items() if v is not None}
    try:
        return json.dumps(call_tool(graph(), name, args).as_dict(), default=str)
    except (ValueError, UnknownService) as e:
        return json.dumps({"error": str(e)})


mcp = MCPServer("blast-radius", instructions=(
    "Tools over a company's service-dependency graph in FalkorDB. Start with rank_root_causes using the names of the "
    "alerting services, then blast_radius, recent_changes, similar_incidents, lessons_for and find_experts on the top candidate. "
    "Every result lists the graph nodes it read under 'cites'."))


@mcp.tool()
def rank_root_causes(alerting: list[str], top_k: int = 5) -> str:
    """Rank which service best explains an alert storm (coverage x precision F1 over sync dependency paths)."""
    return _run("rank_root_causes", alerting=alerting, top_k=top_k)


@mcp.tool()
def blast_radius(service: str) -> str:
    """What breaks if a service fails: failing now (sync) vs at risk (async), features, customers, ARR."""
    return _run("blast_radius", service=service)


@mcp.tool()
def dependencies(service: str, kind: str | None = None, max_hops: int = 6) -> str:
    """What a service relies on, with hop counts. kind: 'sync' or 'async' (optional)."""
    return _run("dependencies", service=service, kind=kind, max_hops=max_hops)


@mcp.tool()
def recent_changes(services: list[str], until_ts: int, window_minutes: int = 120, hops: int = 2) -> str:
    """Deploys to these services and what they sync-depend on, in the window before until_ts (epoch seconds)."""
    return _run("recent_changes", services=services, until_ts=until_ts, window_minutes=window_minutes, hops=hops)


@mcp.tool()
def change_details(deploy_id: str) -> str:
    """Diff summary, author and commits of one deploy."""
    return _run("change_details", deploy_id=deploy_id)


@mcp.tool()
def find_experts(service: str, at_time: int | None = None) -> str:
    """Who to page for a service, timezone-aware (who is awake at at_time, epoch seconds; default now)."""
    return _run("find_experts", service=service, at_time=at_time)


@mcp.tool()
def similar_incidents(service: str, text: str | None = None, limit: int = 5) -> str:
    """Past incidents on this service or its neighborhood, plus what fixed them."""
    return _run("similar_incidents", service=service, text=text, limit=limit)


@mcp.tool()
def lessons_for(service: str) -> str:
    """Learned patterns and fixes (procedural memory) for a service and its dependencies."""
    return _run("lessons_for", service=service)


@mcp.tool()
def critical_services(limit: int = 5) -> str:
    """Chokepoints (betweenness) and most depended-on services (PageRank)."""
    return _run("critical_services", limit=limit)


@mcp.tool()
def path_between(a: str, b: str, max_hops: int = 8) -> str:
    """Shortest dependency path between two services."""
    return _run("path_between", a=a, b=b, max_hops=max_hops)


@mcp.tool()
def suspect_releases(failing: list[str], at_ts: int, window_h: int = 48, hops: int = 2, top_k: int = 5) -> str:
    """PyPI world (GRAPH_NAME=pypi): which release in the window before at_ts explains these failing packages?"""
    from backend.tools.supply_chain import suspect_releases as sr
    try:
        return json.dumps(sr(graph(), failing, at_ts, window_h=window_h, hops=hops, top_k=top_k).as_dict(), default=str)
    except ValueError as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def explore_graph(cypher: str, limit: int = 100) -> str:
    """Read-only Cypher escape hatch (GRAPH.RO_QUERY: the database rejects writes)."""
    try:
        return _run("explore_graph", cypher=cypher, limit=limit)
    except Exception as e:                      # the database refuses writes / bad syntax
        return json.dumps({"error": str(e)})


if __name__ == "__main__":
    if "--http" in sys.argv:
        mcp.run("streamable-http")
    else:
        mcp.run("stdio")
