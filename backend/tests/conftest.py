import time
import uuid

import pytest

from backend.graph.db import drop_graph, get_graph
from backend.world import get_world
from backend.world.loader import load_world

NOW = 1_800_000_000  # fixed "now" so tests are reproducible


@pytest.fixture(scope="session")
def acme_graph():
    name = f"t_acme_{uuid.uuid4().hex[:6]}"
    g = get_graph(name)
    load_world(g, get_world("acme"), now=NOW)
    yield g
    drop_graph(name)


@pytest.fixture(scope="session")
def globex_graph():
    name = f"t_globex_{uuid.uuid4().hex[:6]}"
    g = get_graph(name)
    load_world(g, get_world("globex"), now=NOW)
    yield g
    drop_graph(name)


@pytest.fixture()
def fresh_graph():
    """An empty-ish scratch graph with acme loaded, safe to write to."""
    name = f"t_scratch_{uuid.uuid4().hex[:6]}"
    g = get_graph(name)
    load_world(g, get_world("acme"), now=NOW)
    yield g
    drop_graph(name)
