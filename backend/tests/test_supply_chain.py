"""suspect_releases on a toy ecosystem, and the pypi loader on a toy snapshot."""
import pytest

from backend.graph.db import drop_graph, get_graph
from backend.tools.supply_chain import suspect_releases
from backend.world.pypi import edges, load_pypi

T = 1_700_000_000


def snap():
    pk = lambda reqs, rel: dict(summary="", version="1", requires=reqs, releases=rel, downloads_30d=1)
    return dict(fetched_at=T, packages={
        "core": pk([], [["1.0", T - 90 * 86400], ["2.0", T - 3600]]),               # the culprit: released 1h ago
        "typing": pk([], [["4.0", T - 7200]]),                                      # also released, used by few
        "web": pk([["core", ">=1", False], ["typing", "", False]], [["1.0", T - 400 * 86400]]),
        "api": pk([["core", "", False]], [["1.0", T - 300 * 86400]]),
        "cli": pk([["api", "", False]], [["1.0", T - 300 * 86400]]),
        "docs": pk([["typing", "", True]], [["1.0", T - 300 * 86400]]),             # optional dep: never walked
        "lonely": pk([], [["0.1", T - 10 * 86400]]),
    })


@pytest.fixture()
def g():
    g = get_graph("toy_pypi")
    stats = load_pypi(g, snap())
    assert stats == dict(packages=7, edges=5, releases=8)
    yield g
    drop_graph("toy_pypi")


def test_edges_split_required_and_optional():
    s = snap()
    assert ("web", "core") in edges(s) and ("docs", "typing") not in edges(s)
    assert edges(s, "optional") == [("docs", "typing")]


def test_culprit_explains_failures_through_two_hops(g):
    r = suspect_releases(g, ["web", "api", "cli"], T, window_h=48, hops=2).data
    top = r["suspects"][0]
    assert top["package"] == "core" and top["version"] == "2.0" and top["explains"] == 3 and top["coverage"] == 1.0
    assert [s["package"] for s in r["suspects"]] == ["core", "typing"]
    assert r["suspects"][1]["explains"] == 1


def test_window_excludes_old_releases(g):
    r = suspect_releases(g, ["web", "api"], T - 2 * 3600 - 1, window_h=48).data      # before both releases
    assert r["suspects"] == []


def test_needs_failures(g):
    with pytest.raises(ValueError):
        suspect_releases(g, [], T)
