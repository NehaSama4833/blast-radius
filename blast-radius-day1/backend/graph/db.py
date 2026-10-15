"""Connection to FalkorDB.

If FALKORDB_URL is set we talk to a real server (Docker, FalkorDB Cloud, CI).
Otherwise we start the embedded `falkordblite`, so nothing needs installing.
"""
import os
from functools import lru_cache


@lru_cache(maxsize=1)
def get_db():
    url = os.environ.get("FALKORDB_URL", "").strip()
    if url:
        from falkordb import FalkorDB

        return FalkorDB.from_url(url)
    from redislite.falkordb_client import FalkorDB

    return FalkorDB()


def get_graph(name: str):
    return get_db().select_graph(name)


def drop_graph(name: str) -> None:
    try:
        get_db().select_graph(name).delete()
    except Exception:  # graph did not exist
        pass


def copy_graph(src: str, dest: str):
    """GRAPH.COPY: a fast, fully independent copy (used for sandboxes and benchmarks)."""
    drop_graph(dest)
    get_db().select_graph(src).copy(dest)
    return get_graph(dest)
