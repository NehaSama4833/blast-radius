"""Snapshot the real Python package ecosystem for the `pypi` world.

Downloads the list of the most-downloaded PyPI projects (hugovk/top-pypi-packages, from the public BigQuery
download stats), then each project's JSON metadata from pypi.org: its current `requires_dist` and the upload time
of every release. Writes one compact, gzipped JSON snapshot that `backend/world/pypi.py` loads into FalkorDB.

    python scripts/fetch_pypi.py --top 15000 --out bench/data/pypi_snapshot.json.gz

Only public metadata is fetched (names, dependency specs, release times). No package code is downloaded.
"""
import argparse
import gzip
import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

import requests

TOP_URL = "https://raw.githubusercontent.com/hugovk/top-pypi-packages/main/top-pypi-packages.min.json"
_name_re = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)")


def norm(name: str) -> str:
    """PEP 503 normalised name."""
    return re.sub(r"[-_.]+", "-", name).lower()


def parse_req(spec: str):
    """'urllib3 (<3,>=1.21.1) ; extra == "socks"' -> ('urllib3', '<3,>=1.21.1', optional?)."""
    m = _name_re.match(spec)
    if not m:
        return None
    rest = spec[m.end():]
    marker = rest.split(";", 1)[1] if ";" in rest else ""
    optional = "extra" in marker
    ver = rest.split(";", 1)[0].strip().strip("()").strip()
    if ver.startswith("["):                      # extras of the dependency itself: pkg[security]>=1
        ver = ver.split("]", 1)[1].strip() if "]" in ver else ""
    return norm(m.group(1)), ver[:60], optional


def fetch(session, name):
    for attempt in range(4):
        try:
            r = session.get(f"https://pypi.org/pypi/{name}/json", timeout=30)
            if r.status_code == 404:
                return name, None
            r.raise_for_status()
            d = r.json()
            break
        except Exception:
            if attempt == 3:
                return name, None
            time.sleep(1 + attempt * 2)
    info = d.get("info") or {}
    reqs = []
    for spec in info.get("requires_dist") or []:
        p = parse_req(spec)
        if p:
            reqs.append(p)
    rel = []
    for ver, files in (d.get("releases") or {}).items():
        times = [f.get("upload_time_iso_8601") or f.get("upload_time") for f in files if not f.get("yanked")]
        times = [t for t in times if t]
        if times:
            t = min(times)
            ts = int(datetime.fromisoformat(t.replace("Z", "+00:00")).timestamp())
            rel.append((ver, ts))
    rel.sort(key=lambda x: x[1])
    return name, dict(summary=(info.get("summary") or "")[:120], version=info.get("version"),
                      requires=reqs, releases=rel)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=15000)
    ap.add_argument("--workers", type=int, default=24)
    ap.add_argument("--out", default="bench/data/pypi_snapshot.json.gz")
    a = ap.parse_args()
    top = requests.get(TOP_URL, timeout=60).json()
    rows = top["rows"][: a.top]
    names = [norm(r["project"]) for r in rows]
    downloads = {norm(r["project"]): r["download_count"] for r in rows}
    s = requests.Session()
    s.headers["User-Agent"] = "blast-radius-hackathon-snapshot (graph research; contact via GitHub)"
    out, t0 = {}, time.time()
    with ThreadPoolExecutor(a.workers) as ex:
        futs = [ex.submit(fetch, s, n) for n in names]
        for i, f in enumerate(as_completed(futs), 1):
            n, d = f.result()
            if d:
                d["downloads_30d"] = downloads[n]
                out[n] = d
            if i % 500 == 0:
                print(f"{i}/{len(names)}  {time.time() - t0:.0f}s", file=sys.stderr, flush=True)
    snap = dict(source=TOP_URL, top_list_updated=top.get("last_update"), fetched_at=int(time.time()),
                n=len(out), packages=out)
    with gzip.open(a.out, "wt", encoding="utf-8") as fh:
        json.dump(snap, fh, separators=(",", ":"))
    print(f"wrote {len(out)} packages to {a.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
