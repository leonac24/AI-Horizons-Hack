"""Evaluate a user-built plan: a mix of buildings placed on one lot in the 3D view.

Each typology in the plan is run through the evidence engine at the number of
homes the plan gives it; the results are then combined:

- counts add up (homes, homes serving local need, infrastructure load)
- per-home measures are home-weighted averages (income needed, monthly cost,
  share above local rents, carbon per household)
- the zoning path is the most restrictive path among the plan's building types,
  and dimensional rules are checked against the plan's total homes

Like the engine, this module never sees a weight.
"""

from __future__ import annotations

from pydantic import BaseModel

from core.config import Config
from core.engine import CarbonSeries, HouseholdCheck, analyze
from core.metrics import Metric, Samples, weakest
from core.zoning import Check, ZoningResult, evaluate, load_rules

# Which metrics add up across building types; everything else is a per-home
# measure and is averaged by homes.
SUMMED = {"demand.units_serving_need", "infrastructure.load_index", "units.count"}
# Most restrictive first. Roles come from zoning.yaml, so no status id appears here.
ROLE_ORDER = ["prohibited", "unreviewed", "variance", "discretionary", "permitted"]


class Placement(BaseModel):
    typology_id: str
    count: int


class PlanResult(BaseModel):
    units: int
    by_typology: dict[str, int]  # typology id -> buildings
    homes_by_typology: dict[str, int]
    metrics: dict[str, Metric]
    zoning: ZoningResult
    zoning_by_typology: dict[str, ZoningResult]
    failed_typologies: list[str]  # building types whose use is prohibited here
    households: list[HouseholdCheck]
    carbon: CarbonSeries
    eligible: bool
    ineligible_reason: str | None = None
    notes: list[str] = []


def _combine(mid: str, parts: list[tuple[int, Metric]]) -> Metric:
    total = sum(u for u, _ in parts) or 1
    first = parts[0][1]
    if mid in SUMMED:
        agg = {k: sum(getattr(m, k) for _, m in parts) for k in ("value", "low", "high")}
    elif mid.startswith("feasibility."):
        # The plan can only move as fast as its slowest approval.
        agg = {k: min(getattr(m, k) for _, m in parts) for k in ("value", "low", "high")}
    else:
        agg = {k: sum(u * getattr(m, k) for u, m in parts) / total for k in ("value", "low", "high")}
    return Metric(
        id=mid, label=first.label, unit=first.unit,
        value=round(agg["value"], 3), low=round(min(agg["low"], agg["value"]), 3),
        high=round(max(agg["high"], agg["value"]), 3),
        provenance=weakest(*(m.provenance for _, m in parts)),
        sourceIds=sorted({s for _, m in parts for s in m.sourceIds}),
        note=first.note if len(parts) == 1 else "Combined across the building types in this plan.",
        dependsOn=sorted({k for _, m in parts for k in m.dependsOn}),
    )


def analyze_plan(cfg: Config, parcel: dict, placements: list[Placement]) -> PlanResult:
    typs = {t.id: t for t in cfg.typologies}
    counts: dict[str, int] = {}
    for p in placements:
        if p.typology_id not in typs:
            raise KeyError(f"unknown typology {p.typology_id!r}")
        if p.count > 0:
            counts[p.typology_id] = counts.get(p.typology_id, 0) + p.count
    if not counts:
        raise ValueError("a plan needs at least one building")

    homes = {tid: n * typs[tid].building.homes for tid, n in counts.items()}
    total = sum(homes.values())
    lot = float(parcel.get("lot_area_sf") or 0)
    rules = load_rules(cfg)

    # Evidence per building type, pinned to the homes the plan gives it.
    a = analyze(cfg, parcel, Samples(cfg), homes_override=homes)
    by_id = {s.typology_id: s for s in a.scenarios}

    metrics = {mid: _combine(mid, [(homes[tid], by_id[tid].metrics[mid]) for tid in homes])
               for mid in by_id[next(iter(homes))].metrics}

    # Zoning: each type's use rule, with dimensional rules checked at the plan's total homes.
    zres = {tid: evaluate(cfg, rules, parcel.get("zoning"), typs[tid], lot, total) for tid in homes}
    role = {sid: s.role for sid, s in cfg.zoning.statuses.items()}
    worst = min(zres.values(), key=lambda z: ROLE_ORDER.index(role[z.status]))
    checks: dict[str, Check] = {}
    for z in zres.values():
        for c in z.checks:
            if c.rule_id not in checks or not c.passed:
                checks[c.rule_id] = c
    zoning = worst.model_copy(update={"checks": list(checks.values())})
    failed = [tid for tid, z in zres.items() if z.disqualified]

    # Carbon: home-weighted average of the per-household series.
    series = [(homes[tid], by_id[tid].carbon) for tid in homes]
    def wavg(attr: str) -> list[float]:
        n = len(series[0][1].years)
        return [round(sum(u * getattr(c, attr)[i] for u, c in series) / total, 2) for i in range(n)]
    carbon = CarbonSeries(years=series[0][1].years, value=wavg("value"), low=wavg("low"), high=wavg("high"),
                          provenance=weakest(*(c.provenance for _, c in series)))

    # Households: can they afford the plan's average home?
    cost = metrics["affordability.monthly_cost"]
    households = []
    for hh in by_id[next(iter(homes))].households:
        verdict = "yes" if hh.affordable_monthly >= cost.high else "no" if hh.affordable_monthly < cost.low else "maybe"
        households.append(hh.model_copy(update={"verdict": verdict, "cost_monthly": cost, "tenure_match": True,
                                                "note": None}))

    notes: list[str] = []
    fp = sum(n * typs[tid].building.footprint_ft[0] * typs[tid].building.footprint_ft[1] for tid, n in counts.items())
    if lot:
        notes.append(f"Buildings cover about {round(100 * fp / lot)}% of the lot.")
    if zoning.max_units_by_rule is not None and zoning.max_units_by_rule < total:
        notes.append(f"Reviewed lot-area-per-unit rule allows {zoning.max_units_by_rule} homes here; the plan has {total}.")

    return PlanResult(
        units=total, by_typology=counts, homes_by_typology=homes, metrics=metrics, zoning=zoning,
        zoning_by_typology=zres, failed_typologies=failed, households=households, carbon=carbon,
        eligible=not failed, ineligible_reason=zoning.status_label if failed else None, notes=notes,
    )
