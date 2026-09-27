"""Property tax in the evidence layer: what a scenario's homes would pay, what the
public would collect over the horizon, and what the lot pays today. No weight
enters anything here.

Assessed values come from observed county comparables (built by
pipeline/build_comps.py), never from development cost: Allegheny County
assessments are base-year values, so a cost-derived figure would be wrong by
roughly 2x and would duplicate the cost criterion besides.

Every number is an assumptions.yaml entry named in tax.yaml; nothing about the
city's tax structure is written here. Formulas: docs/METHODS.md.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import numpy as np
from pydantic import BaseModel

from core.config import ROOT, Config, Typology
from core.metrics import Metric, Samples, Trace, to_metric, weakest


class RevenueSeries(BaseModel):
    """Cumulative property tax the parcel yields, year 0..horizon, net of any
    reviewed abatement. Same shape as the carbon series so the UI can share a chart."""

    years: list[int]
    value: list[float]
    low: list[float]
    high: list[float]
    provenance: str
    abated_years: int = 0


@lru_cache(maxsize=4)
def _load_comps(path: str, mtime: float) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8")) or {}


def load_comps(cfg: Config) -> dict:
    """The comps table, or {} when the pipeline has not built it (placeholder path)."""
    p = ROOT / cfg.tax.comps.file
    if not p.exists():
        return {}
    return _load_comps(str(p), p.stat().st_mtime)


@dataclass
class AssessedHome:
    """Per-home assessed BUILDING value draws, and where they came from."""

    draws: np.ndarray
    trace: Trace
    provenance: str  # observed | placeholder
    note: str | None = None


def per_home_assessed(cfg: Config, S: Samples, typ: Typology, neighborhood: str | None,
                      comps: dict) -> AssessedHome:
    """Neighborhood comps, else citywide comps, else the placeholder assumption —
    in the order tax.yaml `comps.fallback` declares."""
    table = (comps.get("by_typology") or {}).get(typ.id) or {}
    for level in cfg.tax.comps.fallback:
        row = None
        if level == "neighborhood" and neighborhood:
            row = (table.get("neighborhoods") or {}).get(neighborhood)
        elif level == "citywide":
            row = table.get("citywide")
        if not row:
            continue
        value, lo, hi = float(row["value"]), float(row["low"]), float(row["high"])
        rng = S.stream("assessment_comps", typ.id, level, neighborhood or "")
        draws = rng.uniform(lo, hi, S.n) if hi > lo else np.full(S.n, value)
        note = None if level == "neighborhood" else (
            f"Too few recent comps in this neighborhood; citywide median of {row['n']} buildings used.")
        return AssessedHome(np.concatenate([[value], draws]), Trace({"observed"}, {cfg.assessment_source}),
                            "observed", note)
    t = Trace()
    draws = S.a("assessed_building_value_per_home", typ.id, t)
    return AssessedHome(draws, t, "placeholder", "No assessment comps built yet; placeholder per-home value.")


@dataclass
class TaxResult:
    metrics: dict[str, Metric]
    revenue: RevenueSeries
    monthly_per_home: np.ndarray  # feeds the affordability chain in core/engine.py
    trace_household: Trace
    notes: list[str] = field(default_factory=list)


def _bodies(cfg: Config, S: Samples, trace: Trace) -> list[tuple[str, np.ndarray, np.ndarray]]:
    """(body id, millage draws, homestead exclusion draws) per taxing body."""
    out = []
    for b in cfg.tax.taxing_bodies:
        mills = S.a(b.millage, used=trace)
        excl = S.a(b.homestead_exclusion, used=trace) if b.homestead_exclusion else S.const(0)
        out.append((b.id, mills, excl))
    return out


def scenario_tax(cfg: Config, S: Samples, typ: Typology, units: int, parcel: dict, comps: dict) -> TaxResult:
    """Tax per home, stabilized annual revenue, and cumulative revenue over the
    horizon net of any REVIEWED abatement. Unreviewed programs are not applied and
    mark the horizon metric a placeholder, exactly like an unreviewed zoning rule."""
    years = int(cfg.assumption("analysis_years").value)
    units = max(units, 1)
    land = float(parcel.get("land_value_usd") or 0)
    home = per_home_assessed(cfg, S, typ, parcel.get("neighborhood"), comps)

    t_base = Trace().merge(home.trace)
    if parcel.get("land_value_usd") is not None:
        t_base.add("observed", cfg.assessment_source)
    bodies = _bodies(cfg, S, t_base)
    homestead = typ.tenure_default in cfg.tax.homestead.applies_to_tenure
    land_per_home = land / units

    # Abatement: exempt building value per home per year, per taxing body.
    t_rev = t_base.merge(Trace())
    exempt = {bid: np.zeros((years, S.n + 1)) for bid, _, _ in bodies}
    abated_years = 0
    notes: list[str] = []
    for prog in (a for a in cfg.tax.abatements if typ.use_key in a.eligible_use_keys):
        if not prog.reviewed:
            t_rev.add("placeholder", None)
            notes.append(f"{prog.label}: terms not reviewed yet; revenue shown without it.")
            continue
        yrs = np.clip(np.rint(S.a(prog.years, used=t_rev)), 0, years)  # (n+1,)
        cap = S.a(prog.exempt_assessed_cap_usd, used=t_rev)
        mask = np.arange(years)[:, None] < yrs[None, :]  # (years, n+1)
        per_home = np.where(mask, np.minimum(home.draws, cap)[None, :], 0.0)
        for bid in prog.applies_to_bodies:
            exempt[bid] = np.minimum(exempt[bid] + per_home, home.draws[None, :])
        abated_years = max(abated_years, int(yrs[0]))
        notes.append(f"{prog.label}: {int(yrs[0])} abated years applied.")

    annual_full = S.const(0)  # whole lot, per year, no abatement
    annual = np.zeros((years, S.n + 1))
    for bid, mills, excl in bodies:
        base = home.draws + land_per_home - (excl if homestead else 0)
        annual_full = annual_full + units * np.maximum(base, 0) * mills / 1000
        annual += units * np.maximum(base[None, :] - exempt[bid], 0) * mills / 1000
    per_home_month = annual_full / units / 12
    cumulative = np.vstack([np.zeros((1, S.n + 1)), np.cumsum(annual, axis=0)])

    series = RevenueSeries(
        years=list(range(years + 1)),
        value=[round(float(r[0])) for r in cumulative],
        low=[round(float(np.percentile(r[1:], 5))) for r in cumulative],
        high=[round(float(np.percentile(r[1:], 95))) for r in cumulative],
        provenance=weakest(t_rev.prov(), "modeled"),
        abated_years=abated_years,
    )
    bodies_label = ", ".join(b.label for b in cfg.tax.taxing_bodies)
    metrics = {
        "revenue.public_horizon": to_metric(
            "revenue.public_horizon", f"Public revenue over {years} years", cumulative[-1], "USD", t_rev,
            note=home.note),
        "revenue.annual_stabilized": to_metric(
            "revenue.annual_stabilized", "Property tax per year once fully taxable", annual_full, "USD/yr",
            t_base, note=f"To {bodies_label}, before any abatement."),
        "tax.per_home_monthly": to_metric(
            "tax.per_home_monthly", "Property tax per home", per_home_month, "USD/mo", t_base,
            note="Assessed value x millage; homestead exclusion applied to owner-occupied types."),
    }
    return TaxResult(metrics=metrics, revenue=series, monthly_per_home=per_home_month,
                     trace_household=t_base, notes=notes)


def site_tax_context(cfg: Config, S: Samples, parcel: dict) -> list[Metric]:
    """Does the lot pay tax today, and roughly what. Lot-level, so site context."""
    status = parcel.get("tax_status")
    known = status is not None
    exempt = known and str(status) in cfg.tax.status.exempt_values
    obs = Trace({"observed"}, {cfg.assessment_source})
    t = Trace({"observed"}, {cfg.assessment_source})
    total_mills = S.const(0)
    for b in cfg.tax.taxing_bodies:
        total_mills = total_mills + S.a(b.millage, used=t)
    land = float(parcel.get("land_value_usd") or 0)
    today = S.const(0) if exempt else land * total_mills / 1000
    return [
        to_metric("site.tax_status_today", "Pays property tax today", S.const(0 if exempt else 1), "yes/no", obs,
                  note=f"Assessment tax status: {status}" if known else "Tax status not in the parcel index yet",
                  provenance="observed" if known else "placeholder"),
        to_metric("site.tax_today", "Property tax this lot pays today (vacant)", today, "USD/yr", t,
                  note="Assessed land value x combined millage; zero when the parcel is tax-exempt.",
                  provenance=None if known else "placeholder"),
    ]
