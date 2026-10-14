import asyncio
import json

import pytest

pytest.importorskip("mcp.server.mcpserver")

from backend.tools.registry import TOOLS  # noqa: E402


@pytest.fixture()
def server(acme_graph, monkeypatch):
    import mcp_server.server as srv
    monkeypatch.setattr(srv, "_graph", acme_graph)
    return srv


def test_mcp_exposes_every_read_tool(server):
    listed = asyncio.run(server.mcp.list_tools())
    names = {t.name for t in (listed.tools if hasattr(listed, "tools") else listed)}
    assert names == set(TOOLS)


def _text(result):
    content = result.content if hasattr(result, "content") else result
    first = content[0]
    return first.text if hasattr(first, "text") else str(first)


def test_mcp_call_matches_registry(server):
    out = json.loads(_text(asyncio.run(server.mcp.call_tool("blast_radius", {"service": "kafka"}))))
    assert out["data"]["service"] == "kafka" and "Service:kafka" in out["cites"]


def test_mcp_errors_are_returned_not_raised(server):
    out = json.loads(_text(asyncio.run(server.mcp.call_tool("blast_radius", {"service": "nope"}))))
    assert "unknown service" in out["error"]
    out = json.loads(_text(asyncio.run(server.mcp.call_tool("explore_graph", {"cypher": "CREATE (:X)"}))))
    assert "error" in out
