"""The `npm` world: a large real slice of the JavaScript package registry as a dependency graph in FalkorDB.

Source: bench/data/npm_snapshot.json.gz from scripts/fetch_npm.py (popular packages for ~80 keywords, plus a
breadth-first crawl over their runtime dependencies), or the committed slice bench/data/npm_slice.json.gz (same
packages and edges, only the releases near the replayed incidents). Same schema as the other worlds:
    (:Service {name, layer:'library', language:'javascript', monitored:true})          one per package
    (:Service)-[:DEPENDS_ON {kind:'sync'}]->(:Service)      a runtime `dependencies` entry of the latest version
    (:Deploy {ts, kind:'release', version, removed})-[:TO]->(:Service)   one per published version, real time
`removed` marks versions npm later took down (e.g. colors 1.4.1); npm keeps their publish time.
"""
import gzip
import json
import re
from functools import lru_cache
from pathlib import Path

DATA = Path(__file__).resolve().parents[2] / "bench" / "data"
FULL, SLICE = DATA / "npm_snapshot.json.gz", DATA / "npm_slice.json.gz"


@lru_cache(maxsize=2)
def load_snapshot(path=None):
    path = Path(path) if path else (FULL if FULL.exists() else SLICE)
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        snap = json.load(fh)
    snap["_path"] = str(path)
    return snap


def edges(snap):
    P = snap["packages"]
    return sorted({(n, d) for n, p in P.items() for d, _ in p["deps"] if d in P and d != n})


def _clean(text):
    """Descriptions are free text from the registry; keep plain characters so query parameters always parse."""
    return re.sub(r"[^A-Za-z0-9 .,:;()/+_-]", "", text or "")[:120]


def _batches(rows, n=5000):
    for i in range(0, len(rows), n):
        yield rows[i:i + n]


def load_npm(graph, snap=None):
    snap = snap or load_snapshot()
    P = snap["packages"]
    graph.query("CREATE INDEX FOR (s:Service) ON (s.name)")
    graph.query("CREATE INDEX FOR (d:Deploy) ON (d.ts)")
    graph.query("CREATE (:Meta {world: 'npm', loaded_at: $t, packages: $n})", {"t": snap["fetched_at"], "n": len(P)})
    for b in _batches([dict(name=n, s=_clean(p.get("description"))) for n, p in P.items()]):
        graph.query("UNWIND $rows AS r CREATE (:Service {name:r.name, layer:'library', tier:3, language:'javascript', "
                    "monitored:true, summary:r.s})", {"rows": b})
    es = edges(snap)
    for b in _batches([list(e) for e in es]):
        graph.query("UNWIND $rows AS e MATCH (a:Service {name:e[0]}), (b:Service {name:e[1]}) "
                    "CREATE (a)-[:DEPENDS_ON {kind:'sync'}]->(b)", {"rows": b})

    def releases():                                 # streamed: 5 M+ rows never sit in memory at once
        for n, p in P.items():
            gone = set(p.get("removed", []))
            for v, t in p["releases"]:
                yield dict(ts=t, v=v, n=n, x=v in gone)
    n_rel, batch = 0, []
    for r in releases():
        batch.append(r)
        if len(batch) == 10000:
            _load_releases(graph, batch)
            n_rel += len(batch)
            batch = []
    if batch:
        _load_releases(graph, batch)
        n_rel += len(batch)
    return dict(packages=len(P), edges=len(es), releases=n_rel)


def _load_releases(graph, rows):
    # lean nodes (5 M+ of them): id and summary are derivable as name@version, so they are not stored
    graph.query("UNWIND $rows AS r MATCH (s:Service {name:r.n}) "
                "CREATE (:Deploy {ts:r.ts, kind:'release', version:r.v, removed:r.x})-[:TO]->(s)", {"rows": rows})
