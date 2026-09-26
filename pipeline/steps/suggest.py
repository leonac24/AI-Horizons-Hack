"""Suggested lots: spread across neighborhoods and site conditions, not favorites."""

from __future__ import annotations

import random


def pick_suggested(records: list[dict], rule: dict, seed: int = 0) -> list[str]:
    """Greedy pick: at most one per neighborhood; each pick prefers a combination of
    stratum values (zoning district, hazard flags, public) not yet covered."""
    rng = random.Random(seed)
    pool = [r for r in records if (r.get("lot_area_sf") or 0) >= rule["min_lot_area_sf"] and r.get("neighborhood")]
    rng.shuffle(pool)
    strata = rule["strata"]
    chosen: list[dict] = []
    used_hoods: set[str] = set()
    seen: dict[str, set] = {s: set() for s in strata}

    def novelty(r: dict) -> int:
        return sum(1 for s in strata if _val(r, s) not in seen[s])

    while len(chosen) < rule["count"]:
        candidates = [r for r in pool if r["neighborhood"] not in used_hoods]
        if not candidates:
            break
        best = max(candidates, key=novelty)
        chosen.append(best)
        used_hoods.add(best["neighborhood"])
        for s in strata:
            seen[s].add(_val(best, s))
    return [r["id"] for r in chosen]


def _val(r: dict, key: str):
    return r.get("zoning") if key == "zoning_district" else r.get(key)
