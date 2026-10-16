"""Snapshot a large, real slice of the npm registry for the `npm` world.

Seeds: the most popular packages for ~80 common keywords (npm's own search, sorted by popularity). Then a breadth-first
crawl over each package's runtime `dependencies` (latest version), until --max packages. For every package we keep
its latest `dependencies` and the publish time of every version (npm keeps the time even for versions it later
removed, e.g. colors 1.4.1). Writes one gzipped JSON snapshot that backend/world/npm.py loads into FalkorDB.

    python scripts/fetch_npm.py --max 60000 --out bench/data/npm_snapshot.json.gz

Only public registry metadata (names, dependency ranges, publish times). No package code is downloaded.
"""
import argparse
import gzip
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from datetime import datetime

import requests

KEYWORDS = """react vue angular svelte webpack babel typescript eslint jest mocha test cli express http server framework
css sass postcss tailwind ui component router redux state graphql api rest fetch ajax promise async stream file fs path
util utility string array object date time format parse json yaml xml csv markdown template logger log color terminal
console command args config env database sql mongodb redis orm crypto hash uuid security auth jwt validation schema
image svg canvas chart animation browser dom polyfill bundler build compiler lint format prettier node aws cloud docker
plugin loader preset gulp grunt rollup vite esbuild swc next nuxt gatsby electron mobile react-native ionic cordova
jquery bootstrap material icons font i18n locale intl email smtp websocket socket realtime queue worker cron job
cache storage s3 upload download compress zip tar gzip image-processing pdf excel word html dom-parser scraper
crawler puppeteer playwright selenium testing assertion mock spy coverage benchmark performance monitoring metrics
analytics tracking seo sitemap rss oauth passport session cookie cors helmet proxy http2 grpc protobuf graphql-client
apollo prisma sequelize typeorm mongoose knex postgres mysql sqlite elasticsearch kafka rabbitmq aws-sdk azure gcp
firebase stripe payment twilio slack discord telegram bot ai openai llm math random crypto-js bignumber decimal
geo map leaflet three webgl game audio video stream media ffmpeg serial usb bluetooth iot arduino raspberry
""".split()
REG = "https://registry.npmjs.org/"
# culprits of the replayed incidents (bench/npm_incidents.py) are always included; their dependents are not forced
FORCE = ["colors", "faker", "is-promise", "node-ipc", "ua-parser-js", "chalk", "node-fetch", "uuid", "axios", "eslint",
         "left-pad", "event-stream", "coa", "rc", "string-width", "strip-ansi", "got", "glob", "minimatch", "rimraf"]


def seeds(session, pages=4):
    def one(kw, frm):
        for attempt in range(3):
            try:
                r = session.get(REG + "-/v1/search", params={"text": f"keywords:{kw}", "size": 250, "from": frm,
                                                            "popularity": 1.0, "quality": 0.0, "maintenance": 0.0}, timeout=60)
                return [o["package"]["name"] for o in r.json().get("objects", [])]
            except Exception:
                time.sleep(1 + attempt)
        return []
    jobs = [(kw, 250 * i) for i in range(pages) for kw in KEYWORDS]
    with ThreadPoolExecutor(8) as ex:
        lists = list(ex.map(lambda a: one(*a), jobs))
    ranked = sorted((frm + pos, k, n) for k, ((kw, frm), l) in enumerate(zip(jobs, lists)) for pos, n in enumerate(l))
    return list(dict.fromkeys(n for _, _, n in ranked))          # most popular per keyword first, across keywords


def ts(iso):
    try:
        return int(datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp())
    except Exception:
        return None


def fetch(session, name):
    for attempt in range(3):
        try:
            r = session.get(REG + name.replace("/", "%2F"), timeout=60)
            if r.status_code == 404:
                return name, None
            r.raise_for_status()
            d = r.json()
            break
        except Exception:
            if attempt == 2:
                return name, None
            time.sleep(1 + 2 * attempt)
    latest = (d.get("dist-tags") or {}).get("latest")
    v = (d.get("versions") or {}).get(latest) or {}
    deps = sorted((v.get("dependencies") or {}).items())
    times = d.get("time") or {}
    rel = sorted(((k, ts(t)) for k, t in times.items() if k not in ("created", "modified", "unpublished") and ts(t)),
                 key=lambda x: x[1])
    removed = sorted(k for k, _ in rel if k not in (d.get("versions") or {}))
    return name, dict(latest=latest, deps=[[n, str(r)[:40]] for n, r in deps], releases=rel, removed=removed,
                      description=(d.get("description") or "")[:120])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max", type=int, default=60000)
    ap.add_argument("--workers", type=int, default=32)
    ap.add_argument("--out", default="bench/data/npm_snapshot.json.gz")
    a = ap.parse_args()
    s = requests.Session()
    adapter = requests.adapters.HTTPAdapter(pool_connections=a.workers, pool_maxsize=a.workers)
    s.mount("https://", adapter)
    s.headers["User-Agent"] = "blast-radius-hackathon-snapshot (graph research)"
    seed = list(dict.fromkeys(seeds(s) + FORCE))
    print(f"{len(seed)} seeds", file=sys.stderr)
    from collections import deque
    seed = FORCE + [n for n in seed if n not in FORCE]
    queued, out = set(), {}
    deps_q, seed_q = deque(), deque(seed)          # dependencies of fetched packages go first, so edges are complete
    t0 = time.time()

    def next_name():
        while deps_q or seed_q:
            n = deps_q.popleft() if deps_q else seed_q.popleft()
            if n not in queued:
                queued.add(n)
                return n
        return None

    with ThreadPoolExecutor(a.workers) as ex:
        pending = set()
        while True:
            while len(pending) < a.workers * 4 and len(out) + len(pending) < a.max:
                n = next_name()
                if n is None:
                    break
                pending.add(ex.submit(fetch, s, n))
            if not pending:
                break
            done, pending = wait(pending, return_when=FIRST_COMPLETED)
            for f in done:
                n, d = f.result()
                if not d:
                    continue
                out[n] = d
                deps_q.extend(dep for dep, _ in d["deps"] if dep not in queued)
                if len(out) % 5000 == 0:
                    print(f"{len(out)} packages, {time.time() - t0:.0f}s", file=sys.stderr, flush=True)
    snap = dict(source="registry.npmjs.org", seeds=len(seed), keywords=KEYWORDS, fetched_at=int(time.time()),
                n=len(out), packages=out)
    with gzip.open(a.out, "wt", encoding="utf-8") as fh:
        json.dump(snap, fh, separators=(",", ":"))
    print(f"wrote {len(out)} packages to {a.out} in {time.time() - t0:.0f}s", file=sys.stderr)


if __name__ == "__main__":
    main()
