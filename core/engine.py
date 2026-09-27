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
from core.zoning import ZoningResult, buildable_margins, cite, evaluate, load_rules


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


class SiteFact(BaseModel):
    id: str
    label: str
    value: str
    provenance: str
    sourceIds: list[str]
    note: str


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
    site_facts: list[SiteFact] = []
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
    estimated_front, estimated_depth = parcel.get("geometry_frontage_ft"), parcel.get("geometry_depth_ft")
    if estimated_front and estimated_depth:
        context = cfg.city.model_dump().get("context") or {}
        source = (context.get("parcel_boundaries") or {}).get("source")
        return LotShape(
            frontage_ft=float(estimated_front), depth_ft=float(estimated_depth),
            provenance="modeled", sourceIds=[source] if source else [],
            note=("Approximate axes from the county parcel polygon's minimum rotated rectangle. "
                  "Not legal frontage or a survey."),
        )
    ratio = cfg.assumption("lot_depth_to_frontage_ratio")
    front = math.sqrt(area / ratio.value) if area > 0 else 0.0
    return LotShape(frontage_ft=round(front, 1), depth_ft=round(area / front, 1) if front else 0.0,
                    provenance="placeholder", sourceIds=[s for s in [ratio.source] if s],
                    note="No usable dimensions in the legal description; drawn from lot area and a "
                         "placeholder depth-to-frontage ratio.")

def _interval_samples(S: Samples, parcel: dict, key: str, value: float,
                      low: float | None, high: float | None) -> np.ndarray:
    """Use a parcel's published estimate and uncertainty, not a citywide stand-in."""
    lo = float(value if low is None else low)
    hi = float(value if high is None else high)
    rng = S.stream("site-context", str(parcel.get("id", "")), key)
    draws = rng.uniform(lo, hi, S.n) if hi > lo else np.full(S.n, value)
    return np.concatenate([[value], draws])


def pure_buildings(typ: Typology, shape: LotShape, lot_area_sf: float,
                   margins: dict[str, float] | None = None) -> tuple[int, bool]:
    """How many of this typology's building fit side by side along the frontage
    (up to max_in_a_row), and whether the form fits the lot at all. When the
    district's setbacks are in force, only the buildable area inside them counts;
    party-wall forms skip the side yards (§ 903.03(c)). Screening geometry only:
    access and topography are not modeled."""
    m = margins or {}
    sides = 0.0 if typ.building.party_walls else m.get("left", 0.0) + m.get("right", 0.0)
    width = shape.frontage_ft - sides
    depth = shape.depth_ft - m.get("front", 0.0) - m.get("rear", 0.0)
    w, d = typ.building.footprint_ft
    fits = (w <= width and d <= depth and lot_area_sf >= typ.min_lot_sf_for_form)
    n = max(1, min(typ.building.max_in_a_row, math.floor(width / w))) if fits else 1
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
    context_sources = cfg.city.model_dump().get("context") or {}
    acs_source = (context_sources.get("acs") or {}).get("source")
    income_est = parcel.get("tract_median_household_income")
    t_ctx = Trace()
    if income_est is None:
        income_local = S.a("tract_median_household_income", used=t_ctx)
        income_note = "Tract estimate unavailable; citywide placeholder shown."
    else:
        t_ctx.add("observed", acs_source)
        income_moe = parcel.get("tract_median_household_income_moe")
        income_local = _interval_samples(
            S, parcel, "income", float(income_est),
            max(0, float(income_est) - float(income_moe)) if income_moe is not None else None,
            float(income_est) + float(income_moe) if income_moe is not None else None)
        income_note = "2020–2024 ACS tract estimate; range uses published 90% margin of error."
    burden_est = parcel.get("tract_renter_cost_burden_share")
    t_burden = Trace()
    if burden_est is None:
        burden = S.a("tract_renter_cost_burden_share", used=t_burden)
        burden_note = "Tract estimate unavailable; citywide placeholder shown."
    else:
        t_burden.add("modeled", acs_source)
        burden = _interval_samples(S, parcel, "rent-burden", float(burden_est),
                                   parcel.get("tract_renter_cost_burden_low"),
                                   parcel.get("tract_renter_cost_burden_high"))
        burden_note = ("2020–2024 ACS tract renters with gross rent at 30%+ of income, "
                       "excluding not-computed. Range is an approximate component-MOE envelope, "
                       "not a Census-published ratio MOE.")
    t_access = Trace()
    transit_access = parcel.get("transit_access_index")
    transit_source = (context_sources.get("transit_jobs") or {}).get("source")
    if transit_access is None:
        access = S.a("jobs_access_index", used=t_access)
        access_note = "EPA transit-access value unavailable for this block group; fallback assumption shown."
        access_provenance = "placeholder"
    else:
        access = S.const(float(transit_access))
        t_access.add("observed", transit_source)
        access_note = ("EPA SLD D5DRI: block-group transit-job access relative to the highest "
                       "block group in its CBSA; 2021-vintage data.")
        access_provenance = "observed"
    t_sewer = Trace()
    sewer = S.a("sewer_stress_index", used=t_sewer)
    obs = Trace({"observed"}, {cfg.assessment_source})

    land_value = parcel.get("land_value_usd")
    site_context = [
        to_metric("site.lot_area_sf", "Lot area", S.const(lot), "sf", obs, provenance="observed"),
        to_metric("site.land_value", "Assessed land value (not a market price)", S.const(land_value or 0), "USD",
                  obs, note=None if land_value is not None else "missing in assessment",
                  provenance="observed" if land_value is not None else "placeholder"),
        to_metric("site.tract_median_income", "Tract median household income", income_local,
                  "USD/yr", t_ctx, note=income_note,
                  provenance="observed" if income_est is not None else "placeholder"),
        to_metric("site.renter_cost_burden", "Tract renters paying 30%+ of income", burden * 100,
                  "%", t_burden, note=burden_note,
                  provenance="modeled" if burden_est is not None else "placeholder"),
        to_metric("site.jobs_access", "Transit access to jobs (regional relative index)",
                  access, "index (0–1)", t_access, note=access_note,
                  provenance=access_provenance),
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

    fema_source = (context_sources.get("flood") or {}).get("source")
    flood_zones = parcel.get("fema_flood_zones")
    if flood_zones:
        flood_value = ("Mapped high-risk flood area" if parcel.get("fema_sfha") else
                       "Mapped outside high-risk flood area") + f" · zone {', '.join(flood_zones)}"
        flood_note = (f"{parcel.get('fema_join_method')}; July 2026 FEMA map screen. "
                      "Another part of the lot may cross a zone boundary.")
    else:
        flood_value = "No mapped zone match"
        flood_note = "No mapped polygon matched this lot; flood status remains unknown."
    sewer_source = (context_sources.get("combined_sewersheds") or {}).get("source")
    sheds = parcel.get("combined_sewershed_ids")
    site_facts = [
        SiteFact(id="site.fema_flood", label="FEMA flood map", value=flood_value,
                 provenance="observed" if flood_zones else "placeholder",
                 sourceIds=[fema_source] if fema_source else [], note=flood_note),
        SiteFact(id="site.combined_sewershed", label="Combined sewershed",
                 value=", ".join(sheds) if sheds else "No mapped combined-sewershed match",
                 provenance="observed" if sheds else "placeholder",
                 sourceIds=[sewer_source] if sewer_source else [],
                 note=(f"{parcel.get('sewershed_join_method')}; 2018 PWSA boundary. "
                       "This does not measure sewer capacity or overflow pressure.") if sheds else
                       "Outside or unmatched in the 2018 layer; sewer type and capacity are unknown."),
    ]
    transit_jobs = parcel.get("transit_jobs_accessible")
    if transit_jobs is not None:
        site_facts.append(SiteFact(
            id="site.transit_jobs_accessible",
            label="Jobs accessible within a 45-minute transit commute",
            value=f"{transit_jobs:,.0f} (distance-decay weighted)",
            provenance="observed",
            sourceIds=[transit_source] if transit_source else [],
            note=("EPA SLD D5BR; 2021-vintage estimate using 2020 GTFS/transit times and "
                  "2017 LEHD jobs. It is not a current schedule or household commute prediction."),
        ))

    # --- Shared affordability inputs --------------------------------------------
    t_inc = Trace()
    ami4 = S.a("ami_4person", used=t_inc)
    share = S.a("housing_cost_share", used=t_inc)
    site_context.insert(0, to_metric(
        "site.area_mfi", "FY2026 Pittsburgh HUD area median family income",
        ami4, "USD/yr", Trace({"observed"}, {cfg.assumption("ami_4person").source}),
        note="Pittsburgh HUD Metro FMR Area baseline, not this tract or household's income.",
        provenance="observed"))
    size_factor = cfg.assumption("household_size_factor").by_size or {}

    shape = lot_shape(cfg, parcel)
    # Width-conditional zoning rules only resolve on an observed frontage.
    observed_frontage = shape.frontage_ft if shape.provenance == "observed" else None
    margins = buildable_margins(cfg, rules, parcel.get("zoning"))
    scenarios: list[Scenario] = []
    for typ in cfg.typologies:
        if homes_override and typ.id not in homes_override:
            continue
        # Fit is judged on the lot itself. Title Nine lets new development use
        # contextual setbacks (§ 925.06) that match the neighbours, which is how
        # most narrow city lots get built, so the full § 903.03 yards are reported
        # and drawn but do not rule a form out.
        n_buildings, form_fits = pure_buildings(typ, shape, lot)
        units = homes_override[typ.id] if homes_override else n_buildings * typ.building.homes
        notes: list[str] = []
        w, d = typ.building.footprint_ft
        if not form_fits and not homes_override:
            notes.append(f"This building ({w:.0f}×{d:.0f} ft) doesn't fit a {shape.frontage_ft:.0f}×"
                         f"{shape.depth_ft:.0f} ft lot, or the lot is under {typ.min_lot_sf_for_form:,.0f} sf.")
        elif margins and not pure_buildings(typ, shape, lot, margins)[1]:
            notes.append(f"This building ({w:.0f}×{d:.0f} ft) fits the lot but not inside the full setbacks; "
                         "it would rely on contextual setbacks that match neighbouring buildings "
                         f"({cite(cfg, cfg.zoning.contextual_setbacks_section)}).")
        zres = evaluate(cfg, rules, parcel.get("zoning"), typ, lot, units, observed_frontage)
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
        vmt = S.a("vmt_per_household_yr", used=t_c)
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
                                note="No zoning rule in force here yet — range covers every possible outcome.",
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
        f.provenance == "placeholder" for f in site_facts) + sum(
        m.provenance == "placeholder" for s in scenarios for m in s.metrics.values())
    return Analysis(parcel=parcel, lot_shape=shape, config_hash=cfg.hash,
                    site_context=site_context, site_facts=site_facts, scenarios=scenarios,
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
    shape = lot_shape(cfg, parcel)
    z = evaluate(cfg, rules, parcel.get("zoning"), typ, lot, units,
                 shape.frontage_ft if shape.provenance == "observed" else None)
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
