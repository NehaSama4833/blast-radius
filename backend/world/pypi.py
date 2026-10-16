"""The `pypi` world: the real Python package ecosystem as a dependency graph in FalkorDB.

Source: bench/data/pypi_snapshot.json.gz, made by scripts/fetch_pypi.py from public PyPI metadata (the 15,000
most-downloaded projects, each one's current `requires_dist`, and the upload time of every release).

Mapped onto the same schema as the company worlds, so the same Cypher, tools and agents work on it:
    (:Service {name, layer:'library', language:'python', monitored:true, downloads_30d})   one per package
    (:Service)-[:DEPENDS_ON {kind:'sync'}]->(:Service)          a required dependency (both packages in the set)
    (:Service)-[:DEPENDS_ON {kind:'optional'}]->(:Service)      an extra (pip install pkg[extra]); never walked
    (:Deploy {id, ts, kind:'release', version, summary})-[:TO]->(:Service)   one per release, real upload time
Dependency edges are as of the snapshot date (packages change their requirements over time); release times are
historical. The README and docs/ECOSYSTEMS.md say so wherever results are reported.
"""
import gzip
import json
from functools import lru_cache
from pathlib import Path

SNAPSHOT = Path(__file__).resolve().parents[2] / "bench" / "data" / "pypi_snapshot.json.gz"


@lru_cache(maxsize=2)
def load_snapshot(path=str(SNAPSHOT)):
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        return json.load(fh)


def edges(snap, kind="sync"):
    """(dependent, dependency) pairs inside the snapshot. kind='sync' = required, 'optional' = extras only."""
    P = snap["packages"]
    out = set()
    for name, p in P.items():
        for dep, _spec, optional in p["requires"]:
            if dep in P and dep != name and optional == (kind == "optional"):
                out.add((name, dep))
    return sorted(out)


def _batches(rows, n=5000):
    for i in range(0, len(rows), n):
        yield rows[i:i + n]


def load_pypi(graph, snap=None, since_ts=None, with_optional=True):
    """Write the ecosystem into `graph`. `since_ts` keeps only releases uploaded at or after that time."""
    snap = snap or load_snapshot()
    P = snap["packages"]
    graph.query("CREATE INDEX FOR (s:Service) ON (s.name)")
    graph.query("CREATE INDEX FOR (d:Deploy) ON (d.ts)")
    graph.query("CREATE (:Meta {world: 'pypi', loaded_at: $t, snapshot_fetched_at: $f, packages: $n})",
                {"t": snap["fetched_at"], "f": snap["fetched_at"], "n": len(P)})
    svc = [dict(name=n, d=p.get("downloads_30d", 0), s=p.get("summary", "")) for n, p in P.items()]
    for b in _batches(svc):
        graph.query("UNWIND $rows AS r CREATE (:Service {name:r.name, layer:'library', tier:3, language:'python', "
                    "monitored:true, downloads_30d:r.d, summary:r.s})", {"rows": b})
    kinds = ["sync"] + (["optional"] if with_optional else [])
    n_edges = 0
    for kind in kinds:
        es = edges(snap, kind)
        n_edges += len(es)
        for b in _batches([list(e) for e in es]):
            graph.query("UNWIND $rows AS e MATCH (a:Service {name:e[0]}), (b:Service {name:e[1]}) "
                        "CREATE (a)-[:DEPENDS_ON {kind:$k}]->(b)", {"rows": b, "k": kind})
    rel = [dict(id=f"{n}=={v}", ts=t, v=v, n=n) for n, p in P.items() for v, t in p["releases"]
           if since_ts is None or t >= since_ts]
    for b in _batches(rel, 10000):
        graph.query("UNWIND $rows AS r MATCH (s:Service {name:r.n}) "
                    "CREATE (:Deploy {id:r.id, ts:r.ts, kind:'release', version:r.v, summary:r.n + ' ' + r.v, "
                    "diff:'', author:''})-[:TO]->(s)", {"rows": b})
    return dict(packages=len(P), edges=n_edges, releases=len(rel))
