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
