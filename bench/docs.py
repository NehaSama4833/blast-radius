"""Condition B ("docs-only"): the SAME facts as the graph, rendered as Markdown pages, plus BM25 search.

The docs-only agent gets `search_docs(query)` and `read_doc(path)`. No graph, no dependency traversal: it has to
find and read pages like a typical RAG agent would. Same facts, same step budget, same model as condition A.
"""
import math
import re
import time
from collections import Counter

from backend.world import topology as topo

TOKEN = re.compile(r"[a-z0-9][a-z0-9\-]*")


def _ts(now, age_s):
    return time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(now - age_s))


def render_docs(world, outcome=None, now=1_800_000_000):
    """Return {path: markdown}. `outcome` (a failure-model Outcome) adds the live alert log and the triggering deploys."""
    docs = {}
    svcs = topo.svc_map(world)
    teams = {t["name"]: t for t in world["teams"]}
    deploys = list(world["deploys"]) + (list(outcome.deploys) if outcome else [])
    for s in world["services"]:
        n = s["name"]
        deps = [d for d in world["deps"] if d["src"] == n]
        owners = [p for p in world["people"] if p["team"] == s["team"]]
        feats = [f["name"] for f in world["features"] if n in f["services"]]
        lines = [f"# Service: {n}", f"Layer: {s['layer']}. Tier: {s['tier']}. Language: {s['language']}.",
                 f"Monitoring: {'monitored' if s['monitored'] else 'NOT monitored (no alerts of its own)'}.",
                 f"Owned by team {s['team']} ({teams[s['team']]['channel']}).", "", "## Depends on"]
        lines += [f"- {d['dst']} ({d['kind']})" for d in deps] or ["- nothing"]
        lines += ["", "## Features that use it"] + ([f"- {f}" for f in feats] or ["- none"])
        lines += ["", "## Owning team members"] + [f"- {p['name']} (@{p['handle']}, {p['timezone']}{', on-call' if p['on_call'] else ''})" for p in owners]
        docs[f"services/{n}.md"] = "\n".join(lines)
    for t in world["teams"]:
        mem = [p for p in world["people"] if p["team"] == t["name"]]
        own = [s["name"] for s in world["services"] if s["team"] == t["name"]]
        docs[f"teams/{t['name']}.md"] = "\n".join([f"# Team: {t['name']}", f"Channel: {t['channel']}", "", "## Members"] + [f"- {p['name']} (@{p['handle']}, {p['timezone']}{', on-call' if p['on_call'] else ''})" for p in mem] + ["", "## Services owned"] + [f"- {s}" for s in own])
    log = ["# Deploy log (newest first)"]
    for d in sorted(deploys, key=lambda x: x["age_s"]):
        log.append(f"- {d['id']} | {_ts(now, d['age_s'])} | {d['kind']} | {d['service']} | by @{d['author']} | {d['summary']}")
    docs["deploys/log.md"] = "\n".join(log)
    for i in world["incidents"]:
        docs[f"postmortems/{i['id']}.md"] = "\n".join([
            f"# Postmortem {i['id']}: {i['title']}", f"Date: {_ts(now, i['age_s'])}. Severity: {i['severity']}.",
            f"Root cause service: {i['root']} (deploy {i['deploy_id']}).", f"Affected: {', '.join(i['affected'])}.",
            f"Summary: {i['summary']}", f"Resolution: {i['resolution']} Time to resolve: {i['ttr_min']} minutes.", f"Responders: {', '.join('@' + h for h in i['responders'])}."])
    for rb in world["runbooks"]:
        docs[f"runbooks/{rb['service']}.md"] = f"# Runbook: {rb['title']}\nService: {rb['service']}\n{rb['steps']}"
    if outcome:
        al = ["# Active alerts"] + [f"- {a['id']} | {_ts(now, a['age_s'])} | {a['service']} | {a['signal']} | {a['severity']}" for a in sorted(outcome.alerts, key=lambda x: -x["age_s"])]
        docs["alerts/active.md"] = "\n".join(al)
    return docs


class BM25:
    def __init__(self, docs, k1=1.5, b=0.75):
        self.paths = sorted(docs)
        self.tf = [Counter(TOKEN.findall(docs[p].lower())) for p in self.paths]
        self.len = [sum(c.values()) for c in self.tf]
        self.avg = sum(self.len) / len(self.len)
        self.df = Counter(t for c in self.tf for t in c)
        self.N, self.k1, self.b = len(self.paths), k1, b

    def search(self, query, k=5):
        q = TOKEN.findall(query.lower())
        scores = []
        for i, c in enumerate(self.tf):
            s = 0.0
            for t in q:
                if t in c:
                    idf = math.log(1 + (self.N - self.df[t] + 0.5) / (self.df[t] + 0.5))
                    s += idf * c[t] * (self.k1 + 1) / (c[t] + self.k1 * (1 - self.b + self.b * self.len[i] / self.avg))
            if s > 0:
                scores.append((s, self.paths[i]))
        scores.sort(key=lambda x: (-x[0], x[1]))
        return scores[:k]


class DocStore:
    """The two tools the docs-only agent gets."""

    def __init__(self, docs):
        self.docs, self.index = docs, BM25(docs)
        self.seen = set()

    def search_docs(self, query, k=5):
        hits = self.index.search(query, k)
        self.seen.update(p for _, p in hits)
        return [dict(path=p, score=round(s, 3), snippet=self.docs[p][:160].replace("\n", " ")) for s, p in hits]

    def read_doc(self, path):
        if path not in self.docs:
            raise ValueError(f"no such document: {path}")
        self.seen.add(path)
        return self.docs[path][:6000]
