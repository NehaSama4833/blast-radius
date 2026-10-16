"""Scenario generator: 10 dev + 20 held-out test scenarios across difficulty tiers.

A scenario is a small, committed JSON spec (world, roots, change kind, noise, seed).
`materialize` re-runs the failure model to get alerts + ground truth. Generated once, committed
BEFORE any test-split evaluation, and a test (test_scenarios_frozen) fails if it ever changes.
"""
import json
import random
from pathlib import Path

from backend.world import get_world
from backend.world import failure
from backend.world import topology as topo

SCENARIO_DIR = Path(__file__).resolve().parents[2] / "bench" / "scenarios"

# (tier -> count) per split. Totals: dev 10, test 20.
PLAN = {
    "dev": {"easy": 2, "medium": 3, "hard": 4, "ambiguous": 1},
    "test": {"easy": 4, "medium": 6, "hard": 8, "ambiguous": 2},
}
HARD_NOISE = dict(flaky=True, missing=True, distractors=2)


def _roots_for(world, tier):
    svcs = topo.svc_map(world)
    out = []
    for name, s in svcs.items():
        dep = topo.sync_dependents(world, name)
        mon_dep = [d for d in dep if svcs[d]["monitored"]]
        if tier == "easy" and s["monitored"] and not mon_dep and not topo.async_dependents(world, name):
            out.append(name)                                            # one alert, direct cause
        elif tier == "medium" and not s["monitored"] and mon_dep and max(dep[d] for d in mon_dep) >= 2:
            out.append(name)                                            # silent culprit, 2+ hops down
        elif tier == "hard" and not s["monitored"] and len(mon_dep) >= 4:
            out.append(name)                                            # silent, big storm, + noise
    return sorted(out)


def _ambiguous_pairs(world):
    svcs = topo.svc_map(world)
    silent = [n for n, s in svcs.items() if not s["monitored"]]
    pairs = []
    for i, a in enumerate(silent):
        for b in silent[i + 1:]:
            da, db = set(topo.sync_dependents(world, a)), set(topo.sync_dependents(world, b))
            if len(da) >= 2 and len(db) >= 2 and not (da <= db or db <= da) and len(da & db) <= max(1, min(len(da), len(db)) // 3):
                pairs.append([a, b])
    return pairs


def generate_specs():
    rng = random.Random(20261015)
    worlds = {"acme": get_world("acme"), "globex": get_world("globex")}
    used = set()
    specs = {"dev": [], "test": []}
    # test split draws first from roots dev did not use, so held-out scenarios are as new as possible
    for split in ("dev", "test"):
        for tier, count in PLAN[split].items():
            for k in range(count):
                wname = "globex" if (k % 3 == 2) else "acme"
                w = worlds[wname]
                if tier == "ambiguous":
                    cands = [p for p in _ambiguous_pairs(w) if tuple(p) not in used] or _ambiguous_pairs(w)
                    roots = rng.choice(cands)
                else:
                    cands = [r for r in _roots_for(w, tier) if (wname, r) not in used] or _roots_for(w, tier)
                    roots = [rng.choice(cands)]
                used.add(tuple(roots) if tier == "ambiguous" else (wname, roots[0]))
                noise = HARD_NOISE if tier in ("hard", "ambiguous") else dict(flaky=False, missing=False, distractors=0)
                specs[split].append(dict(
                    id=f"{split}-{tier}-{k + 1}", split=split, tier=tier, world=wname, roots=roots,
                    change_kind=rng.choice(failure.CHANGE_KINDS), noise=noise, seed=rng.randint(1, 10**6)))
    return specs


# Extended held-out split: added Oct 16, frozen BEFORE any held-out run (test or extended).
# Same failure model, a new seed, three worlds; boutique is the real Online Boutique topology (see world/boutique.py).
PLAN_EXT = {
    "acme": {"easy": 5, "medium": 9, "hard": 11, "ambiguous": 5},
    "globex": {"easy": 4, "medium": 6, "hard": 10},            # globex has no two-cause pair that fits the rules
    "boutique": {"easy": 2, "medium": 3, "hard": 5},
}


def _roots_ext(world, tier):
    r = _roots_for(world, tier)
    if r or tier != "hard":
        return r
    svcs = topo.svc_map(world)          # small worlds: any silent service that takes 2+ monitored services down
    return sorted(n for n, s in svcs.items() if not s["monitored"]
                  and sum(1 for d in topo.sync_dependents(world, n) if svcs[d]["monitored"]) >= 2)


def generate_extended():
    rng = random.Random(20261016)
    out = []
    for wname, plan in PLAN_EXT.items():
        w = get_world(wname)
        for tier, count in plan.items():
            for k in range(count):
                roots = rng.choice(_ambiguous_pairs(w)) if tier == "ambiguous" else [rng.choice(_roots_ext(w, tier))]
                noise = HARD_NOISE if tier in ("hard", "ambiguous") else dict(flaky=False, missing=False, distractors=0)
                out.append(dict(id=f"ext-{wname}-{tier}-{k + 1}", split="extended", tier=tier, world=wname, roots=roots,
                                change_kind=rng.choice(failure.CHANGE_KINDS), noise=noise, seed=rng.randint(1, 10**6)))
    return out


def materialize(spec):
    """Re-run the failure model for a spec. Returns (world, Outcome)."""
    world = get_world(spec["world"])
    rng = random.Random(spec["seed"])
    outs = []
    for i, root in enumerate(spec["roots"]):
        first = 5 * 60 + i * 60                       # ambiguous roots start a minute apart
        outs.append(failure.break_service(world, root, spec["change_kind"], spec["noise"], rng,
                                          _id_offset=i * 4, _first_alert_age=first + rng.randint(0, 120)))
    out = outs[0] if len(outs) == 1 else failure.merge(world, outs)
    failure.finalize_alert_ids(out)
    out.truth["tier"] = spec["tier"]
    return world, out


def write_specs():
    SCENARIO_DIR.mkdir(parents=True, exist_ok=True)
    specs = generate_specs()
    specs["extended"] = generate_extended()
    for split, items in specs.items():
        (SCENARIO_DIR / f"{split}.json").write_text(json.dumps(items, indent=2, sort_keys=True) + "\n")
    return specs


def load_specs(split):
    return json.loads((SCENARIO_DIR / f"{split}.json").read_text())


if __name__ == "__main__":
    s = write_specs()
    print({k: len(v) for k, v in s.items()})
