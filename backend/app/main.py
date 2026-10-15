"""FastAPI app. No free-text input anywhere: every field is a pick from a list, validated against the graph."""
import json
import os
import queue
import random
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from backend.actions.discord import post_incident
from backend.agents.memory import record_resolution
from backend.agents.runner import run_investigation
from backend.agents.llm_policy import LLMPolicy
from backend.app.limits import DailyCap, RateLimiter
from backend.graph import sandbox
from backend.graph.db import get_graph
from backend.world import CONFIGS, failure, get_world, topology as topo
from backend.world.history import CHANGE_KINDS
from backend.world.loader import load_world

REPLAY_FILE = Path(__file__).with_name("replay.json")
WORLDS = tuple(CONFIGS)
ACTIONS = ("rollback", "config", "scale", "hotfix", "restart")

def _cleanup_loop():
    while True:
        time.sleep(600)
        try:
            sandbox.cleanup_expired()
        except Exception:
            pass                                  # a failed sweep must never take the API down


@asynccontextmanager
async def lifespan(_app):
    threading.Thread(target=_cleanup_loop, daemon=True).start()     # drops sandboxes older than their 2h life
    yield


app = FastAPI(title="Blast Radius", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=[o for o in os.environ.get("ALLOWED_ORIGINS", "http://localhost:5173").split(",") if o],
                   allow_methods=["GET", "POST"], allow_headers=["*"])

limiter = RateLimiter(n=int(os.environ.get("RATE_LIMIT_PER_MIN", "30")), per_s=60)
daily = DailyCap(int(os.environ.get("DAILY_INVESTIGATION_CAP", "200")))
_posts = RateLimiter(n=5, per_s=60)
_tmpl_lock = threading.Lock()


def _client_ip(req: Request) -> str:
    return (req.headers.get("x-forwarded-for", "").split(",")[0].strip() or (req.client.host if req.client else "unknown"))


def _guard(req: Request):
    if not limiter.allow(_client_ip(req)):
        raise HTTPException(429, "too many requests, slow down")


def ensure_template(world: str):
    with _tmpl_lock:
        g = get_graph(world)
        if g.query("MATCH (s:Service) RETURN count(s)").result_set[0][0] == 0:
            load_world(g, get_world(world), now=time.time())
    return g


def _sandbox_graph(name: str):
    if not name.startswith(sandbox.PREFIX) or name not in sandbox.list_sandboxes():
        raise HTTPException(404, "unknown or expired sandbox")
    return get_graph(name)


def _world_of(g) -> str:
    return g.query("MATCH (m:Meta) RETURN m.world").result_set[0][0]


class NewSandbox(BaseModel):
    world: str


class Chaos(BaseModel):
    sandbox: str
    service: str | None = None
    change_kind: str | None = None
    surprise: bool = False


class Investigate(BaseModel):
    sandbox: str


class Resolve(BaseModel):
    sandbox: str
    investigation: str = Field(pattern=r"^inv-\d+$")
    action: str
    ttr_min: float = Field(gt=0, le=1440)


class Post(BaseModel):
    sandbox: str
    investigation: str = Field(pattern=r"^inv-\d+$")


@app.get("/api/health")
def health():
    return dict(ok=True, worlds=WORLDS)


@app.get("/api/worlds")
def worlds():
    return dict(worlds=[dict(name=w, services=len(CONFIGS[w]["services"])) for w in WORLDS], actions=ACTIONS, change_kinds=CHANGE_KINDS)


@app.post("/api/sandbox")
def new_sandbox(body: NewSandbox, req: Request):
    _guard(req)
    if body.world not in WORLDS:
        raise HTTPException(400, "unknown world")
    ensure_template(body.world)
    try:
        return dict(sandbox=sandbox.create_sandbox(body.world), world=body.world)
    except sandbox.SandboxLimit as e:
        raise HTTPException(503, str(e))


@app.get("/api/graph/{name}")
def graph_view(name: str, req: Request):
    _guard(req)
    g = _sandbox_graph(name)
    now = int(time.time())
    nodes = [dict(id=n, layer=l, tier=t, monitored=m, team=tm, culprit_hint=None) for n, l, t, m, tm in g.query(
        "MATCH (s:Service)-[:OWNED_BY]->(t:Team) RETURN s.name, s.layer, s.tier, s.monitored, t.name ORDER BY s.name").result_set]
    edges = [dict(source=a, target=b, kind=k) for a, b, k in g.query("MATCH (a:Service)-[r:DEPENDS_ON]->(b:Service) RETURN a.name, b.name, r.kind").result_set]
    alerting = [r[0] for r in g.query("MATCH (a:Alert)-[:ON]->(s:Service) WHERE a.ts >= $since RETURN DISTINCT s.name ORDER BY s.name", {"since": now - 3600}).result_set]
    return dict(nodes=nodes, edges=edges, alerting=alerting)


@app.post("/api/chaos")
def chaos(body: Chaos, req: Request):
    _guard(req)
    g = _sandbox_graph(body.sandbox)
    world = get_world(_world_of(g))
    rng = random.Random()
    if body.surprise:
        svcs = topo.svc_map(world)
        cands = [n for n, s in svcs.items() if not s["monitored"] and sum(1 for d in topo.sync_dependents(world, n) if svcs[d]["monitored"]) >= 4]
        service, kind, noise = rng.choice(sorted(cands)), rng.choice(CHANGE_KINDS), dict(flaky=True, missing=True, distractors=2)
    else:
        if body.service not in topo.svc_map(world):
            raise HTTPException(400, "unknown service")
        if body.change_kind not in CHANGE_KINDS:
            raise HTTPException(400, "unknown change kind")
        service, kind, noise = body.service, body.change_kind, {}
    existing = g.query("MATCH (d:Deploy) RETURN count(d)").result_set[0][0]
    o = failure.break_service(world, service, kind, noise, rng, _id_offset=existing - len(world["deploys"]))
    failure.apply_outcome(g, o, int(time.time()))
    # the response never reveals the culprit: that is the point of the game
    return dict(alerting=o.alerting, n_alerts=len(o.alerts))


def make_policy():
    """Claude-backed agents when a key is configured (and USE_RULES is not set); otherwise the deterministic rule policy."""
    if os.environ.get("USE_RULES") or not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("OPENROUTER_API_KEY")):
        return None
    try:
        return LLMPolicy()
    except Exception:
        return None


def _stream_events(events):
    for e in events:
        yield f"data: {json.dumps(e, default=str)}\n\n"


@app.post("/api/investigate")
def investigate(body: Investigate, req: Request):
    _guard(req)
    g = _sandbox_graph(body.sandbox)
    now = int(time.time())
    alerting = [r[0] for r in g.query("MATCH (a:Alert)-[:ON]->(s:Service) WHERE a.ts >= $since RETURN DISTINCT s.name", {"since": now - 3600}).result_set]
    if not alerting:
        raise HTTPException(400, "no recent alerts: press a chaos button first")
    if not daily.take():
        return _replay()
    q: queue.Queue = queue.Queue()

    def work():
        try:
            run_investigation(g, alerting, now=now, emit=q.put, policy=make_policy())
        except Exception as e:                    # never leave the stream hanging
            q.put(dict(type="error", agent="Lead", text=f"investigation failed: {type(e).__name__}"))
        q.put(None)

    threading.Thread(target=work, daemon=True).start()

    def gen():
        while (e := q.get()) is not None:
            yield f"data: {json.dumps(e, default=str)}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


def _replay():
    if not REPLAY_FILE.exists():
        raise HTTPException(503, "daily investigation cap reached and no replay available")
    events = json.loads(REPLAY_FILE.read_text())
    for e in events:
        e["replay"] = True
    banner = dict(type="notice", agent="Lead", text="Daily live-investigation cap reached. Showing a recorded replay.", replay=True)
    return StreamingResponse(_stream_events([banner] + events), media_type="text/event-stream")


@app.post("/api/resolve")
def resolve(body: Resolve, req: Request):
    _guard(req)
    g = _sandbox_graph(body.sandbox)
    if body.action not in ACTIONS:
        raise HTTPException(400, "unknown action")
    try:
        return record_resolution(g, body.investigation, body.action, f"Resolved by {body.action}", body.ttr_min)
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.post("/api/post")
def post(body: Post, req: Request):
    _guard(req)
    g = _sandbox_graph(body.sandbox)
    r = g.query("MATCH (:Investigation {id:$i})-[:CONCLUDED]->(d:Decision) RETURN d.message", {"i": body.investigation}).result_set
    if not r or not r[0][0]:
        raise HTTPException(404, "no drafted message for that investigation")
    if not _posts.allow("global"):
        raise HTTPException(429, "posting is rate limited")
    return post_incident(r[0][0])           # the server posts ITS OWN drafted text, never text from the client
