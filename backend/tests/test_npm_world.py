"""The npm loader on a toy snapshot, and suspect_releases over it (removed versions keep their real time)."""
from backend.graph.db import drop_graph, get_graph
from backend.tools.supply_chain import suspect_releases
from backend.world.npm import edges, load_npm

T = 1_640_000_000


def toy():
    pk = lambda deps, rel, removed=(): dict(latest=rel[-1][0], deps=[[d, "^1"] for d in deps], releases=rel, removed=list(removed))
    return dict(fetched_at=T, packages={
        "colors": pk([], [["1.4.0", T - 800 * 86400], ["1.4.1", T - 3600]], removed=["1.4.1"]),
        "winston": pk(["colors"], [["3.0.0", T - 900 * 86400]]),
        "cli-app": pk(["winston"], [["1.0.0", T - 100 * 86400]]),
        "prompt": pk(["colors", "outside-the-set"], [["1.0.0", T - 300 * 86400]]),
    })


def test_toy_npm_world():
    g = get_graph("toy_npm")
    try:
        assert load_npm(g, toy()) == dict(packages=4, edges=3, releases=5)
        assert ("prompt", "outside-the-set") not in edges(toy())
        assert g.query("MATCH (d:Deploy {version:'1.4.1'})-[:TO]->(:Service {name:'colors'}) RETURN d.removed").result_set == [[True]]
        top = suspect_releases(g, ["winston", "cli-app", "prompt"], T, window_h=48).data["suspects"][0]
        assert top["package"] == "colors" and top["version"] == "1.4.1" and top["coverage"] == 1.0
    finally:
        drop_graph("toy_npm")
