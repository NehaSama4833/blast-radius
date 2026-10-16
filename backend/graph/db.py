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


def copy_graph(src: str, dest: str, attempts: int = 4):
    """GRAPH.COPY: a fast, fully independent copy (used for sandboxes, simulations and benchmarks).

    The server forks to take the copy; under memory or process pressure the fork can fail ("could not fork").
    That is transient, so retry with a short backoff before giving up."""
    import time
    drop_graph(dest)
    for i in range(attempts):
        try:
            get_db().select_graph(src).copy(dest)
            return get_graph(dest)
        except Exception as e:
            if "fork" not in str(e).lower() or i == attempts - 1:
                raise
            time.sleep(0.2 * (2 ** i))
