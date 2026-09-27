"""Assessment comparables: what the county assesses EXISTING buildings of each
housing type at, per home, by neighborhood. Pure functions; no I/O."""

from __future__ import annotations

import statistics
from collections import defaultdict

from core.config import Config

# (neighborhood, per-home value at the band midpoint, at the band's low edge, at its high edge)
Comp = tuple[str | None, float, float, float]


def per_home_values(cfg: Config, rows: list[dict]) -> dict[str, list[Comp]]:
    """typology id -> one Comp per qualifying row of that typology's use classes.

    A multi-unit class is a unit band, so one parcel's per-home value is
    building_value / homes with homes anywhere in the band. Dividing by the low
    edge gives the highest per-home value the row supports, by the high edge the
    lowest; those bound the range the engine draws from."""
    classes = cfg.tax.comps.use_classes
    since = cfg.tax.comps.built_since_year
    typologies_for: dict[str, list[str]] = defaultdict(list)
    for t in cfg.typologies:
        for uc in t.assessment_use_classes:
            typologies_for[uc].append(t.id)
    out: dict[str, list[Comp]] = defaultdict(list)
    for r in rows:
        uc = r.get("use_class")
        if uc not in classes:
            continue
        try:
            value = float(r.get("building_value") or 0)
            year = int(float(r.get("year_built") or 0))
        except (TypeError, ValueError):
            continue
        if value <= 0 or year < since:
            continue
        spec = classes[uc]
        lo_homes, hi_homes = spec.band()
        for tid in typologies_for[uc]:
            out[tid].append((r.get("neighborhood"), value / spec.homes, value / lo_homes, value / hi_homes))
    return out


def _quantile(sorted_vals: list[float], q: float) -> float:
    pos = q * (len(sorted_vals) - 1)
    lo, hi = int(pos), min(int(pos) + 1, len(sorted_vals) - 1)
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (pos - lo)


def _summary(comps: list[Comp], q: tuple[float, float]) -> dict:
    """Median of the midpoint values; `low` is the lower quantile of the smallest
    per-home reading each row supports, `high` the upper quantile of the largest.
    With quantiles straddling 0.5 this guarantees low <= value <= high."""
    return {
        "value": round(statistics.median(c[1] for c in comps)),
        "low": round(_quantile(sorted(c[3] for c in comps), q[0])),
        "high": round(_quantile(sorted(c[2] for c in comps), q[1])),
        "n": len(comps),
    }


def aggregate_comps(cfg: Config, rows: list[dict]) -> dict:
    """The table core/tax.py reads: per typology, a citywide row and one row per
    neighborhood with at least `min_comps` comps. Row keys: id, use_class,
    building_value, year_built, neighborhood."""
    rule = cfg.tax.comps
    table: dict = {}
    for tid, comps in per_home_values(cfg, rows).items():
        by_hood: dict[str, list[Comp]] = defaultdict(list)
        for c in comps:
            if c[0]:
                by_hood[c[0]].append(c)
        table[tid] = {
            "citywide": _summary(comps, rule.quantiles) if len(comps) >= rule.min_comps else None,
            "neighborhoods": {h: _summary(v, rule.quantiles) for h, v in sorted(by_hood.items())
                              if len(v) >= rule.min_comps},
        }
    return {"config_hash": cfg.hash, "built_since_year": rule.built_since_year,
            "min_comps": rule.min_comps, "by_typology": table}
