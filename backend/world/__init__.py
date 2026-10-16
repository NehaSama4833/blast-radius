from functools import lru_cache
import copy

from backend.world import acme, boutique, globex
from backend.world.history import build_world

CONFIGS = {"acme": acme.CONFIG, "globex": globex.CONFIG, "boutique": boutique.CONFIG}


@lru_cache(maxsize=None)
def _cached(name):
    return build_world(CONFIGS[name])


def get_world(name):
    """A fresh deep copy of the (deterministic) world dict."""
    return copy.deepcopy(_cached(name))
