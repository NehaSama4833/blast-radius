"""Faithfulness check for free text written by a model (or by templates).

Every *name* in the text (a service of this graph, a deploy id d-N, an incident id INC-N) must be a node the
writer actually saw in a tool result, and every *number* above 10 must appear in some tool result (directly,
as a list length, or as a percentage of a 0-1 score). Anything else is flagged. Small numbers (0-10) are
ignored: they are too common ("2 hours", "3 findings") to check without false alarms.
"""
import json
import re

ID_RE = re.compile(r"\b(d-\d+|INC-\d+)\b")
NUM_RE = re.compile(r"(?<![\w.-])(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d+))?")


def numbers_in(obj, out=None):
    """All numbers a tool result 'contains': values, list lengths, 0-1 scores as percentages, numbers inside strings."""
    out = set() if out is None else out
    if isinstance(obj, bool) or obj is None:
        return out
    if isinstance(obj, (int, float)):
        out.add(_norm(obj))
        if isinstance(obj, float) and 0 <= obj <= 1:
            out.add(_norm(round(obj * 100)))
        return out
    if isinstance(obj, str):
        for m in NUM_RE.finditer(obj):
            out.add(_norm(float(m.group(1).replace(",", "") + ("." + m.group(2) if m.group(2) else ""))))
        return out
    if isinstance(obj, dict):
        for v in obj.values():
            numbers_in(v, out)
        return out
    if isinstance(obj, (list, tuple, set)):
        out.add(str(len(obj)))
        for v in obj:
            numbers_in(v, out)
    return out


def _norm(x):
    x = float(x)
    return str(int(x)) if x == int(x) else f"{x:.4f}".rstrip("0").rstrip(".")


def check(text, seen_cites, numbers, service_names):
    """Returns dict(names=n_checked, numbers=n_checked, flagged=[...]) for one piece of text."""
    text = str(text or "")
    keys = {c.split(":", 1)[1] for c in seen_cites if ":" in c}
    flagged, n_names, n_nums = [], 0, 0
    names = set(ID_RE.findall(text)) | {s for s in service_names if re.search(rf"(?<![\w-]){re.escape(s)}(?![\w-])", text)}
    for name in sorted(names):
        n_names += 1
        if name not in keys:
            flagged.append(f"name {name} was not in any tool result this agent read")
    stripped = ID_RE.sub(" ", text)
    for s in service_names:                                  # service names like "auth-v2" must not count as numbers
        stripped = stripped.replace(s, " ")
    for m in NUM_RE.finditer(stripped):
        raw = m.group(1).replace(",", "")
        val = float(raw + ("." + m.group(2) if m.group(2) else ""))
        if val <= 10:
            continue
        n_nums += 1
        if _norm(val) not in numbers and _norm(round(val)) not in numbers:
            flagged.append(f"number {m.group(0)} does not appear in any tool result (it may be derived, or wrong)")
    return dict(names=n_names, numbers=n_nums, flagged=flagged)


def check_many(texts, seen_cites, numbers, service_names):
    tot = dict(names=0, numbers=0, flagged=[])
    for t in texts:
        r = check(t, seen_cites, numbers, service_names)
        tot["names"] += r["names"]; tot["numbers"] += r["numbers"]; tot["flagged"] += r["flagged"]
    return tot
