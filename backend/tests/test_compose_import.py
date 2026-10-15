import pytest

from backend.graph.db import drop_graph, get_graph
from backend.tools.ranking import rank_root_causes
from backend.world.compose_import import compose_to_world
from backend.world.loader import load_world

COMPOSE = """
services:
  web:
    build: .
    ports: ["80:80"]
    depends_on: [api]
    healthcheck: {test: ["CMD", "true"]}
  api:
    build: ./api
    depends_on: [db, cache, events]
    healthcheck: {test: ["CMD", "true"]}
  worker:
    build: ./worker
    depends_on: [events, db]
    healthcheck: {test: ["CMD", "true"]}
  db:
    image: postgres:16
  cache:
    image: redis:7
    healthcheck: {test: ["CMD", "true"]}
  events:
    image: redpanda
    healthcheck: {test: ["CMD", "true"]}
"""


def test_compose_rules():
    w, notes = compose_to_world(COMPOSE)
    by = {s["name"]: s for s in w["services"]}
    assert by["db"]["layer"] == "data" and by["web"]["layer"] == "edge" and by["events"]["layer"] == "core"
    assert by["db"]["monitored"] is False and by["api"]["monitored"] is True
    kinds = {(d["src"], d["dst"]): d["kind"] for d in w["deps"]}
    assert kinds[("api", "db")] == "sync" and kinds[("api", "events")] == "async"
    assert any("db: no healthcheck" in n for n in notes)


def test_bad_compose_is_rejected():
    with pytest.raises(ValueError):
        compose_to_world("version: '3'")


def test_imported_system_runs_through_the_ranker():
    w, _ = compose_to_world(COMPOSE, "t_compose")
    drop_graph("t_compose")
    g = get_graph("t_compose")
    load_world(g, w, now=1_800_000_000)
    r = rank_root_causes(g, ["web", "api", "worker"]).data
    assert r["candidates"][0]["candidate"] == "db"          # the silent database under all three
    drop_graph("t_compose")
