"""Per-parcel analysis: every typology in config, every metric with a range and
provenance. Evidence only — weights never enter here.

Metric formulas are documented in docs/METHODS.md; keep the two in sync.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
from pydantic import BaseModel

from core.config import Config, Typology
from core.metrics import Metric, Samples, Trace, to_metric, weakest
from core.zoning import ZoningResult, evaluate, load_rules


class HouseholdCheck(BaseModel):
    household_id: str
    verdict: str  # "yes" | "maybe" | "no"
    affordable_monthly: float
    cost_monthly: Metric
    tenure_match: bool
    note: str | None = None


class CarbonSeries(BaseModel):
    years: list[int]
    value: list[float]
    low: list[float]
    high: list[float]
    provenance: str


class Scenario(BaseModel):
    typology_id: str
    units: int
    buildings: int
    form_fits: bool
    notes: list[str]
    metrics: dict[str, Metric]
    zoning: ZoningResult
    households: list[HouseholdCheck]
    carbon: CarbonSeries
    # Mirrors zoning.disqualified so a client never has to know which zoning
    # statuses are hard stops. Disqualified scenarios are still returned in full —
    # a CDC needs to see what it cannot do, and why — but they must be presented
    # outside the ranking, not scored against it.
    eligible: bool = True
    ineligible_reason: str | None = None


class LotShape(BaseModel):
    """Frontage and depth in feet, for drawing the lot. Observed when the deed
    legal description gave dimensions that agree with the assessed area."""

    frontage_ft: float
    depth_ft: float
    provenance: str
    sourceIds: list[str]
    note: str


class Analysis(BaseModel):
    parcel: dict[str, Any]
    lot_shape: LotShape
    config_hash: str
    site_context: list[Metric]
    scenarios: list[Scenario]
    placeholder_count: int
    # Server-side answer to "what may be ranked". The browser scores only these.
    rankable_typology_ids: list[str] = []
    excluded_typology_ids: list[str] = []


def _hazard_flags(cfg: Config, parcel: dict) -> dict[str, bool | None]:
    return {k: parcel.get(k) for k in cfg.hazards}


def lot_shape(cfg: Config, parcel: dict) -> LotShape:
    area = float(parcel.get("lot_area_sf") or 0)
    front, depth = parcel.get("frontage_ft"), parcel.get("depth_ft")
    if front and depth:
        return LotShape(frontage_ft=float(front), depth_ft=float(depth), provenance="observed",
                        sourceIds=[cfg.assessment_source],
                        note="From the deed legal description; agrees with the assessed lot area.")
    ratio = cfg.assumption("lot_depth_to_frontage_ratio")
    front = math.sqrt(area / ratio.value) if area > 0 else 0.0
    return LotShape(frontage_ft=round(front, 1), depth_ft=round(area / front, 1) if front else 0.0,
                    provenance="placeholder", sourceIds=[s for s in [ratio.source] if s],
                    note="No usable dimensions in the legal description; drawn from lot area and a "
                         "placeholder depth-to-frontage ratio.")


def pure_buildings(typ: Typology, shape: LotShape, lot_area_sf: float) -> tuple[int, bool]:
    """How many of this typology's building fit side by side along the frontage
    (up to max_in_a_row), and whether the form fits the lot at all. Screening
    geometry only: setbacks, access and topography are not modeled."""
    w, d = typ.building.footprint_ft
    fits = (w <= shape.frontage_ft and d <= shape.depth_ft and lot_area_sf >= typ.min_lot_sf_for_form)
    n = max(1, min(typ.building.max_in_a_row, math.floor(shape.frontage_ft / w))) if fits else 1
    return n, fits


def analyze(cfg: Config, parcel: dict, samples: Samples | None = None,
            homes_override: dict[str, int] | None = None) -> Analysis:
    """`homes_override` pins a typology's home count (work backwards, mixed plans)."""
    S = samples or Samples(cfg)
    rules = load_rules(cfg)
    lot = float(parcel.get("lot_area_sf") or 0)
    flags = _hazard_flags(cfg, parcel)
    hazards_cfg = cfg.hazards

    # --- Lot context (same for every scenario) ----------------------------------
    t_ctx = Trace()
    income_local = S.a("tract_median_household_income", used=t_ctx)
    t_burden = Trace()
    burden = S.a("tract_renter_cost_burden_share", used=t_burden)
    t_access = Trace()
    access = S.a("jobs_access_index", used=t_access)
    t_sewer = Trace()
    sewer = S.a("sewer_stress_index", used=t_sewer)
    obs = Trace({"observed"}, {cfg.assessment_source})

    land_value = parcel.get("land_value_usd")
    site_context = [
        to_metric("site.lot_area_sf", "Lot area", S.const(lot), "sf", obs, provenance="observed"),
        to_metric("site.land_value", "Assessed land value (not a market price)", S.const(land_value or 0), "USD",
                  obs, note=None if land_value is not None else "missing in assessment",
                  provenance="observed" if land_value is not None else "placeholder"),
        to_metric("site.tract_median_income", "Median household income nearby", income_local, "USD/yr", t_ctx),
        to_metric("site.renter_cost_burden", "Renters paying 30%+ of income nearby", burden * 100, "%", t_burden),
        to_metric("site.jobs_access", "Transit access to jobs (city avg = 1)", access, "index", t_access),
        to_metric("site.sewer_stress", "Combined-sewer stress (city avg = 1)", sewer, "index", t_sewer),
    ]
    for flag, spec in hazards_cfg.items():
        val = flags.get(flag)
        src = cfg.sources.sources[spec["source"]]
        site_context.append(to_metric(
            f"site.{flag}", spec["label"], S.const(1 if val else 0), "yes/no",
            Trace({"observed"}, {spec["source"]}),
            note="Tested at the parcel centroid" if val is not None else f"{src.name} not loaded",
            provenance="observed" if val is not None else "placeholder"))

    # --- Shared affordability inputs --------------------------------------------
    t_inc = Trace()
    ami4 = S.a("ami_4person", used=t_inc)
    share = S.a("housing_cost_share", used=t_inc)
    size_factor = cfg.assumption("household_size_factor").by_size or {}

    shape = lot_shape(cfg, parcel)
    scenarios: list[Scenario] = []
    for typ in cfg.typologies:
        if homes_override and typ.id not in homes_override:
            continue
        n_buildings, form_fits = pure_buildings(typ, shape, lot)
        units = homes_override[typ.id] if homes_override else n_buildings * typ.building.homes
        notes: list[str] = []
        if not form_fits and not homes_override:
            w, d = typ.building.footprint_ft
            notes.append(f"This building ({w:.0f}×{d:.0f} ft) doesn't fit a "
                         f"{shape.frontage_ft:.0f}×{shape.depth_ft:.0f} ft lot, or the lot is under "
                         f"{typ.min_lot_sf_for_form:,.0f} sf.")
        zres = evaluate(cfg, rules, parcel.get("zoning"), typ, lot, units)
        if zres.max_units_by_rule is not None and zres.max_units_by_rule < units:
            notes.append(f"Zoning lot-area-per-unit allows {zres.max_units_by_rule} units here; showing {units} as planned.")

        # Cost to build
        t_cost = Trace()
        gross_sf = units * typ.unit_size_sf
        hard = S.a("hard_cost_psf", typ.id, t_cost)
        soft = S.a("soft_cost_share", used=t_cost)
        site_share = S.const(0)
        for flag in hazards_cfg:
            if flags.get(flag):
                site_share = site_share + S.a(f"{flag}_cost_share", used=t_cost)
                notes.append(f"{hazards_cfg[flag]['label']}: added site cost range applied.")
        land = S.const(float(land_value or 0))
        if land_value is not None:
            t_cost.add("observed", cfg.assessment_source)
        dev_cost = gross_sf * hard * (1 + soft + site_share) + land
        per_unit = dev_cost / units

        cap = S.a("annual_capital_cost_share", used=t_cost)
        opex = S.a("operating_cost_per_unit_month", used=t_cost)
        monthly = per_unit * cap / 12 + opex
        t_aff = t_cost.merge(t_inc)
        income_needed = monthly * 12 / share
        ami_needed = income_needed / ami4 * 100

        # Local fit: how affordable is one home to a typical nearby household (0–1).
        afford_ratio = np.clip(income_local / income_needed, 0, 1)
        t_local = t_aff.merge(t_ctx).merge(t_burden)
        demand = units * burden * afford_ratio
        # A SHARE, not a count. Multiplying unit count by a tract cost-burden
        # share by an affordability ratio and reporting the product in whole
        # homes asserted a precision none of those three inputs has, and the old
        # name ("displacement") asserted a causal claim on top of it.
        share_above_local_rents = 1 - afford_ratio

        # Infrastructure load
        t_infra = t_sewer.merge(Trace({"observed"}, {hazards_cfg[f]["source"] for f in hazards_cfg if flags.get(f) is not None}))
        hw = cfg.assumption("infrastructure_hazard_weight")
        t_infra.add(hw.provenance, hw.source)
        mult = 1 + sum((hw.by_key or {}).get(f, 0) for f in hazards_cfg if flags.get(f))
        infra = units * mult * sewer

        # Carbon per household over the horizon
        t_c = Trace()
        years = int(cfg.assumption("analysis_years").value)
        emb = S.a("embodied_kgco2e_psf", typ.id, t_c) * typ.unit_size_sf / 1000  # t per household
        kwh = S.a("operational_kwh_psf_yr", typ.id, t_c) * typ.unit_size_sf
        grid = S.a("grid_kgco2e_per_kwh", used=t_c)
        decarb = S.a("grid_decarbonization_per_yr", used=t_c)
        vmt = S.a("vmt_per_household_yr", used=t_c) / np.maximum(access, 0.1)
        t_c = t_c.merge(t_access)
        kgpm = S.a("kgco2e_per_vmt", used=t_c)
        yr = np.arange(1, years + 1)[:, None]
        annual = (kwh * grid * (1 - decarb) ** (yr - 1) + vmt * kgpm) / 1000  # t/yr, shape (years, n+1)
        cumulative = np.vstack([emb[None, :], emb + np.cumsum(annual, axis=0)])
        cprov = weakest(t_c.prov(), "modeled")
        carbon = CarbonSeries(
            years=list(range(years + 1)),
            value=[round(float(r[0]), 2) for r in cumulative],
            low=[round(float(np.percentile(r[1:], 5)), 2) for r in cumulative],
            high=[round(float(np.percentile(r[1:], 95)), 2) for r in cumulative],
            provenance=cprov,
        )

        # Zoning path score
        zscore = cfg.assumption("zoning_status_score")
        # This one draws from its own stream rather than S.a(), so it has to
        # declare the assumption it rests on itself.
        zt = Trace({"assumption"}, keys={"zoning_status_score"})
        unreviewed_status = cfg.zoning.status_id("unreviewed")
        if zres.status == unreviewed_status:
            # Unknown approval path: the band spans every outcome the code allows.
            # Drawn from the one seeded stream so the band is reproducible and a
            # new assumption elsewhere cannot reshuffle it.
            vals = list((zscore.by_key or {}).values())
            rng = S.stream("zoning_status_score", typ.id)
            zarr = np.concatenate([[zscore.by_key[unreviewed_status]],
                                   rng.uniform(min(vals), max(vals), S.n)])
            zmetric = to_metric("feasibility.zoning_score", "Zoning path score", zarr, "0–1", zt,
                                note="District not reviewed — range covers every possible outcome.",
                                provenance="placeholder")
        else:
            zt.add("observed", cfg.zoning.code.source)
            zmetric = to_metric("feasibility.zoning_score", "Zoning path score",
                                S.const(zscore.by_key[zres.status]), "0–1", zt,
                                note=zres.status_label)

        metrics = {
            "demand.units_serving_need": to_metric(
                "demand.units_serving_need", "Homes a cost-burdened local household could afford", demand, "homes", t_local),
            "feasibility.zoning_score": zmetric,
            "affordability.ami_needed_pct": to_metric(
                "affordability.ami_needed_pct", "Income needed, as % of area median", ami_needed, "% AMI", t_aff),
            "affordability.monthly_cost": to_metric(
                "affordability.monthly_cost", "Monthly cost to cover development + operations", monthly, "USD/mo", t_aff),
            "affordability.dev_cost_per_unit": to_metric(
                "affordability.dev_cost_per_unit", "Development cost per home", per_unit, "USD", t_cost),
            "affordability_gap.share_above_local_rents": to_metric(
                "affordability_gap.share_above_local_rents",
                "Share priced above what nearby renters can pay", share_above_local_rents * 100, "%", t_local,
                note="A pressure indicator, not a count of displaced households. "
                     "A causal estimate needs longitudinal data we do not have."),
            "infrastructure.load_index": to_metric(
                "infrastructure.load_index", "Infrastructure load at this site", infra, "index", t_infra),
            "carbon.per_household_horizon": to_metric(
                "carbon.per_household_horizon", f"Carbon per household over {years} years", cumulative[-1], "tCO2e", t_c),
            "carbon.embodied_per_household": to_metric(
                "carbon.embodied_per_household", "Upfront (embodied) carbon per household", emb, "tCO2e", t_c),
            "units.count": to_metric("units.count", "Homes", S.const(units), "homes", Trace({"modeled"})),
        }

        # Households: could this household afford it?
        hh_checks = []
        for hh in cfg.households.households:
            income = float(ami4[0]) * size_factor.get(hh.size, 1.0) * hh.ami_pct / 100
            affordable = income * float(share[0]) / 12
            m = metrics["affordability.monthly_cost"]
            verdict = "yes" if affordable >= m.high else "no" if affordable < m.low else "maybe"
            hh_checks.append(HouseholdCheck(
                household_id=hh.id, verdict=verdict, affordable_monthly=round(affordable), cost_monthly=m,
                tenure_match=hh.tenure == typ.tenure_default,
                note=None if hh.tenure == typ.tenure_default else f"Usually {typ.tenure_default}-occupied"))

        scenarios.append(Scenario(typology_id=typ.id, units=units, buildings=n_buildings,
                                  form_fits=form_fits, notes=notes,
                                  metrics=metrics, zoning=zres, households=hh_checks, carbon=carbon,
                                  eligible=not zres.disqualified,
                                  ineligible_reason=zres.disqualified_reason))

    n_placeholder = sum(m.provenance == "placeholder" for m in site_context) + sum(
        m.provenance == "placeholder" for s in scenarios for m in s.metrics.values())
    return Analysis(parcel=parcel, lot_shape=shape, config_hash=cfg.hash,
                    site_context=site_context, scenarios=scenarios,
                    placeholder_count=n_placeholder,
                    rankable_typology_ids=[s.typology_id for s in scenarios if s.eligible],
                    excluded_typology_ids=[s.typology_id for s in scenarios if not s.eligible])


def work_backwards(cfg: Config, parcel: dict, typology_id: str, units: int, target_ami_pct: float) -> dict:
    """What would have to change for `units` homes of `typology_id` to reach a target income tier."""
    typ = next((t for t in cfg.typologies if t.id == typology_id), None)
    if typ is None:
        raise KeyError(f"unknown typology {typology_id!r}")
    rules = load_rules(cfg)
    lot = float(parcel.get("lot_area_sf") or 0)
    z = evaluate(cfg, rules, parcel.get("zoning"), typ, lot, units)
    # Re-run the evidence engine with this typology pinned to the requested unit count.
    a = analyze(cfg, parcel, Samples(cfg), homes_override={typology_id: units})
    m = a.scenarios[0].metrics["affordability.monthly_cost"]
    ami4 = cfg.assumption("ami_4person").value
    share = cfg.assumption("housing_cost_share").value
    cap = cfg.assumption("annual_capital_cost_share").value
    affordable = ami4 * target_ami_pct / 100 * share / 12
    gap_monthly = {k: max(0.0, getattr(m, k) - affordable) for k in ("value", "low", "high")}
    subsidy = {k: round(v * 12 / cap) for k, v in gap_monthly.items()}
    failed = [c.model_dump() for c in z.checks if not c.passed]
    infra = [spec["label"] for f, spec in cfg.hazards.items() if parcel.get(f)]
    return {
        "typology_id": typology_id,
        "units": units,
        "target_ami_pct": target_ami_pct,
        "zoning": z.model_dump(),
        "failed_rules": failed,
        "zoning_path": z.status_label,
        "subsidy_per_unit": {"value": subsidy["value"], "low": min(subsidy["low"], subsidy["high"]),
                             "high": max(subsidy["low"], subsidy["high"]), "unit": "USD",
                             "provenance": m.provenance},
        "infrastructure_flags": infra,
        "note": "Subsidy is the up-front capital that closes the gap between cost-covering rent and "
                "30% of the target household's income, at the assumed capital cost.",
    }
