"""Protection for the public site: per-IP rate limit, a global daily investigation cap."""
import threading
import time
from collections import defaultdict, deque


class RateLimiter:
    def __init__(self, n: int, per_s: float):
        self.n, self.per_s, self.hits, self.lock = n, per_s, defaultdict(deque), threading.Lock()

    def allow(self, key: str, now=None) -> bool:
        now = now if now is not None else time.time()
        with self.lock:
            q = self.hits[key]
            while q and now - q[0] > self.per_s:
                q.popleft()
            if len(q) >= self.n:
                return False
            q.append(now)
            return True


class DailyCap:
    def __init__(self, cap: int):
        self.cap, self.day, self.count, self.lock = cap, None, 0, threading.Lock()

    def take(self, now=None) -> bool:
        day = time.strftime("%Y-%m-%d", time.gmtime(now if now is not None else time.time()))
        with self.lock:
            if day != self.day:
                self.day, self.count = day, 0
            if self.count >= self.cap:
                return False
            self.count += 1
            return True


class GraphDailyCap:
    """A daily cap kept in FalkorDB, so a server restart (free hosting restarts often) does not reset it.

    One `(:Cap {name, day, count})` node per cap and UTC day in a small `limits` graph. Writes to one graph are
    serialised by FalkorDB, so the increment is atomic across threads and server instances. Falls back to an
    in-memory cap if the database is unreachable."""

    def __init__(self, cap: int, name: str, graph_name: str = "limits"):
        self.cap, self.name, self.graph_name = cap, name, graph_name
        self.fallback = DailyCap(cap)

    def take(self, now=None) -> bool:
        day = time.strftime("%Y-%m-%d", time.gmtime(now if now is not None else time.time()))
        try:
            from backend.graph.db import get_graph
            r = get_graph(self.graph_name).query(
                "MERGE (c:Cap {name: $n, day: $d}) ON CREATE SET c.count = 0 "
                "WITH c WHERE c.count < $cap SET c.count = c.count + 1 RETURN c.count",
                {"n": self.name, "d": day, "cap": self.cap}).result_set
            return bool(r)
        except Exception:
            return self.fallback.take(now)

    def used(self, now=None) -> int:
        day = time.strftime("%Y-%m-%d", time.gmtime(now if now is not None else time.time()))
        try:
            from backend.graph.db import get_graph
            r = get_graph(self.graph_name).query("MATCH (c:Cap {name: $n, day: $d}) RETURN c.count",
                                                 {"n": self.name, "d": day}).result_set
            return int(r[0][0]) if r else 0
        except Exception:
            return self.fallback.count
