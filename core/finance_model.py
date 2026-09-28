"""Evidence-bounded land and housing finance estimates for Lotline.

This module is deliberately pure Python so the API can call it without loading
the offline GIS pipeline. It consumes already-normalized evidence and never
uses vacant-land assessment as a market price.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from math import isfinite
from statistics import quantiles
from typing import Any

EVIDENCE_FIELDS = (
    "value", "low", "high", "unit", "provenance", "evidence_tier",
    "interval_type", "geography", "source_ids", "source_snapshot_ids",
    "model_id", "model_version", "sample_size", "as_of", "limitations",
    "confirmation_needed",
)


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if isfinite(number) else None


def _date(value: Any) -> date | None:
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


def _assumption(defaults: dict, key: str, *, unit: str | None = None) -> dict | None:
    """Return a normalized range; scalars are accepted but stay explicit assumptions."""
    raw = defaults.get(key)
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        value = _finite(raw)
        if value is None:
            return None
        return {
            "value": value, "low": value, "high": value,
            "unit": unit or "USD", "provenance": "assumption",
            "evidence_tier": "declared_scenario", "interval_type": "scenario_range",
            "geography": "Pittsburgh scenario", "source_ids": [],
            "source_snapshot_ids": [], "model_id": None, "model_version": None,
            "sample_size": None, "as_of": None,
            "limitations": ["Scalar supplied without source metadata; treated as a declared assumption."],
            "confirmation_needed": "Replace with a dated, project-specific input.",
        }
    value, low, high = (_finite(raw.get(k)) for k in ("value", "low", "high"))
    if value is None or low is None or high is None or low > value or value > high:
        return None
    out = {
        "value": value, "low": low, "high": high,
        "unit": raw.get("unit", unit or "USD"),
        "provenance": raw.get("provenance", "assumption"),
        "evidence_tier": raw.get("evidence_tier", "declared_scenario"),
        "interval_type": raw.get("interval_type", "scenario_range"),
        "geography": raw.get("geography", "Pittsburgh scenario"),
        "source_ids": _as_list(raw.get("source_ids", raw.get("source"))),
        "source_snapshot_ids": _as_list(raw.get("source_snapshot_ids", raw.get("vintage"))),
        "model_id": raw.get("model_id"), "model_version": raw.get("model_version"),
        "sample_size": raw.get("sample_size"), "as_of": raw.get("as_of"),
        "limitations": list(raw.get("limitations", [])),
        "confirmation_needed": raw.get("confirmation_needed"),
    }
    return out


def _as_list(value: Any) -> list:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _envelope(value: float | None, low: float | None, high: float | None, unit: str,
              *, provenance: str = "assumption", evidence_tier: str = "declared_scenario",
              interval_type: str = "scenario_range", geography: str | None = None,
              source_ids: list | None = None, snapshots: list | None = None,
              sample_size: int | None = None, as_of: str | None = None,
              limitations: list[str] | None = None, confirmation: str | None = None,
              model_id: str | None = None, model_version: str | None = None) -> dict:
    return {
        "value": value, "low": low, "high": high, "unit": unit,
        "provenance": provenance, "evidence_tier": evidence_tier,
        "interval_type": interval_type, "geography": geography,
        "source_ids": source_ids or [], "source_snapshot_ids": snapshots or [],
        "model_id": model_id, "model_version": model_version,
        "sample_size": sample_size, "as_of": as_of,
        "limitations": limitations or [], "confirmation_needed": confirmation,
    }


def _derived_envelope(value: float | None, low: float | None, high: float | None, unit: str,
                     inputs: list[dict | None], *, evidence_tier: str,
                     interval_type: str = "scenario_range", geography: str | None = None,
                     limitations: list[str] | None = None,
                     confirmation: str | None = None, model_id: str | None = None) -> dict:
    """Envelope for a calculation, retaining the weakest input evidence trail."""
    present = [item for item in inputs if isinstance(item, dict)]
    # A derived calculation cannot be stronger than its least-supported input.
    order = {"observed": 0, "modeled": 1, "assumption": 2, "placeholder": 3}
    provenance = max((item.get("provenance", "placeholder") for item in present),
                     key=lambda label: order.get(label, 3), default="modeled")

    def union(field: str) -> list:
        result = []
        for item in present:
            value = item.get(field)
            values = value if isinstance(value, list) else ([value] if value is not None else [])
            for entry in values:
                if entry not in result:
                    result.append(entry)
        return result

    all_limits = union("limitations")
    for limit in limitations or []:
        if limit not in all_limits:
            all_limits.append(limit)
    confirmations = union("confirmation_needed")
    as_ofs = [str(item["as_of"]) for item in present if item.get("as_of")]
    return _envelope(value, low, high, unit, provenance=provenance,
        evidence_tier=evidence_tier, interval_type=interval_type,
        geography=geography or next((item.get("geography") for item in present if item.get("geography")), None),
        source_ids=union("source_ids"), snapshots=union("source_snapshot_ids"),
        model_id=model_id, model_version="1" if model_id else None,
        sample_size=max((item.get("sample_size") for item in present if isinstance(item.get("sample_size"), int)), default=None),
        as_of=min(as_ofs) if as_ofs else None, limitations=all_limits,
        confirmation=confirmation or "; ".join(str(item) for item in confirmations) or None)


def _land_value(parcel: dict, evidence: dict, defaults: dict, today: date) -> dict:
    area = _finite(parcel.get("lot_area_sf", parcel.get("lot_area_sqft", parcel.get("area_sqft"))))
    raw_sales = evidence.get("county_sales", [])
    if isinstance(raw_sales, dict):
        raw_sales = raw_sales.get("value") or []
    if not isinstance(raw_sales, list):
        raw_sales = []
    target_neighborhood = str(parcel.get("neighborhood") or "").strip().casefold()
    target_zoning = str(parcel.get("zoning") or "").strip().casefold()
    target_lat, target_lon = _finite(parcel.get("lat")), _finite(parcel.get("lon"))
    qualified = []
    for row in raw_sales:
        price, comp_area = _finite(row.get("sale_price")), _finite(row.get("parcel_area_sqft"))
        sold = _date(row.get("sale_date"))
        if (price is None or price <= 0 or comp_area is None or comp_area <= 0 or sold is None
                or sold > today or row.get("arm_length") is not True or row.get("vacant") is not True):
            continue
        age = (today - sold).days / 365.25
        if age > 7:
            continue
        neighborhood = str(row.get("neighborhood") or "").strip().casefold()
        zoning = str(row.get("zoning") or row.get("zoning_district") or "").strip().casefold()
        distance_m = _finite(row.get("distance_m"))
        miles = _finite(row.get("distance_miles"))
        if distance_m is None and miles is not None:
            distance_m = miles * 1609.344
        row_lat, row_lon = _finite(row.get("lat")), _finite(row.get("lon"))
        if distance_m is None and all(v is not None for v in (target_lat, target_lon, row_lat, row_lon)):
            from math import asin, cos, radians, sin, sqrt
            dlat, dlon = radians(row_lat - target_lat), radians(row_lon - target_lon)
            haversine = sin(dlat / 2) ** 2 + cos(radians(target_lat)) * cos(radians(row_lat)) * sin(dlon / 2) ** 2
            distance_m = 6_371_000 * 2 * asin(sqrt(haversine))
        qualified.append((row, price / comp_area, age, comp_area, neighborhood, zoning, distance_m))

    size_pool = [x for x in qualified if area and area > 0 and 0.5 * area <= x[3] <= 2.0 * area]
    candidate_tiers = []
    if target_neighborhood:
        candidate_tiers.append(("neighborhood", [x for x in size_pool if x[4] == target_neighborhood]))
    if target_zoning:
        candidate_tiers.append(("zoning", [x for x in size_pool if x[5] == target_zoning]))
    if target_lat is not None and target_lon is not None:
        candidate_tiers.append(("spatial_1mi", [x for x in size_pool if x[6] is not None and x[6] <= 1609.344]))
    match_tier, pool = "countywide", []
    for tier, candidates in candidate_tiers:
        if len(candidates) >= 3:
            match_tier, pool = tier, candidates
            break
    if not pool and len(size_pool) >= 3:
        match_tier, pool = "county_size_matched", size_pool
    if not pool:
        pool = qualified
    prices = sorted(unit_price for _, unit_price, *_ in pool)
    count = len(prices)
    if count:
        mid = prices[count // 2] if count % 2 else (prices[count // 2 - 1] + prices[count // 2]) / 2
        low_psf, high_psf = prices[0], prices[-1]
        # Spatial matches use quartiles. Broader county fallbacks keep full
        # observed spread because they are less comparable to the subject.
        if count >= 4 and match_tier not in {"countywide", "county_size_matched"}:
            q = quantiles(prices, n=4, method="inclusive")
            low_psf, high_psf = q[0], q[2]
        if area and area > 0:
            vals = (mid * area, low_psf * area, high_psf * area)
            chosen = [x[0] for x in pool]
            is_spatial = match_tier in {"neighborhood", "zoning", "spatial_1mi"}
            limitations = ["Historical consideration is not a current asking price.",
                           "The sale index's vacancy flag reflects current assessment cohort, not verified sale-date vacancy."]
            if not is_spatial:
                limitations.append("No ≥3 neighborhood, zoning, or one-mile match was available; this is a broader county fallback. Lot-size matching alone is not a local comparable match.")
            return {
                "value": _envelope(vals[0], vals[1], vals[2], "USD",
                    provenance="modeled", evidence_tier=f"{match_tier}_sales_estimate",
                    interval_type="unvalidated_comparable_sales_range", geography=f"parcel {match_tier} matches" if is_spatial else "Allegheny County",
                    source_ids=sorted({str(r.get("source_id")) for r in chosen if r.get("source_id")}),
                    snapshots=sorted({str(r.get("snapshot_id")) for r in chosen if r.get("snapshot_id")}),
                    sample_size=count, as_of=max(str(r["sale_date"])[:10] for r in chosen),
                    model_id="county_vacant_land_comparable_estimate", model_version="1",
                    limitations=limitations,
                    confirmation="Confirm title, transfer terms, arm's-length status, site feasibility, and current owner price."),
                "comparable_count": _envelope(count, count, count, "sales",
                    provenance="modeled", evidence_tier=f"{match_tier}_sales_estimate",
                    interval_type="count", geography="Allegheny County", sample_size=count,
                    source_ids=sorted({str(r.get("source_id")) for r in chosen if r.get("source_id")}),
                    snapshots=sorted({str(r.get("snapshot_id")) for r in chosen if r.get("snapshot_id")}),
                    as_of=max(str(r["sale_date"])[:10] for r in chosen)),
            }

    fallback = _assumption(defaults, "land_value", unit="USD")
    if fallback is None:
        assessed = _finite(parcel.get("land_value_usd"))
        if assessed is not None and assessed >= 0:
            fallback = _envelope(assessed, assessed, assessed, "USD", provenance="assumption",
                evidence_tier="assessed_value_acquisition_scenario", interval_type="scenario_point",
                geography="parcel assessment",
                source_ids=_as_list(defaults.get("assessment_source")),
                limitations=["County assessed land value is used only as an acquisition-cost scenario. It is not a sale price, appraisal, asking price, or market-value estimate."],
                confirmation="Replace with verified owner or agency disposition terms and title review.")
    if fallback:
        fallback["limitations"] = list(fallback["limitations"]) + [f"No qualified recent county sale comparables were available (count={count}); this is a declared fallback, not a parcel bid or market quote."]
        fallback["confirmation_needed"] = "Obtain current owner/agency disposition terms and verify title."
        value = fallback
    else:
        value = _envelope(None, None, None, "USD", provenance="placeholder",
            evidence_tier="unresolved", interval_type="unavailable", geography="parcel",
            limitations=[f"No qualified recent county sales support a land-value estimate (count={count})."],
            confirmation="Confirm acquisition price with the owner or disposing agency.")
    return {"value": value, "comparable_count": _envelope(count, count, count, "sales",
        provenance="observed" if count else "placeholder", evidence_tier="county_sales_fallback" if count else "unresolved",
        interval_type="count", geography="Allegheny County", sample_size=count)}


def _resolved(defaults: dict, keys: list[str], unit: str) -> dict | None:
    for key in keys:
        value = _assumption(defaults, key, unit=unit)
        if value is not None:
            return value
    return None


def _scale(env: dict | None, multiplier: float, unit: str = "USD", *,
           inputs: list[dict | None] | None = None, evidence_tier: str | None = None) -> dict:
    if not env:
        return _envelope(None, None, None, unit, provenance="placeholder", evidence_tier="unresolved",
                         interval_type="unavailable", limitations=["Required input is unavailable."])
    return _derived_envelope(env["value"] * multiplier, env["low"] * multiplier,
        env["high"] * multiplier, unit, [env, *(inputs or [])],
        evidence_tier=evidence_tier or env["evidence_tier"],
        interval_type=env["interval_type"], geography=env["geography"],
        model_id=env.get("model_id"))


def _development_cost(gross_sf: float, units: int, land: dict, defaults: dict, parcel: dict) -> dict:
    hard_rate = _resolved(defaults, ["hard_cost_psf"], "USD/sf")
    hard = _scale(hard_rate, gross_sf)
    site_rate = _resolved(defaults, ["site_cost_usd"], "USD")
    site_share = _resolved(defaults, ["site_cost_share"], "share of hard cost")
    hazard_adjustments = {}
    hazard_envs = []
    for flag, key in (("steep_slope", "steep_slope_cost_share"),
                      ("landslide", "landslide_cost_share"),
                      ("undermined", "undermined_cost_share")):
        if parcel.get(flag) is True:
            hazard = _assumption(defaults, key, unit="share of hard cost")
            hazard_adjustments[flag] = hazard or _envelope(None, None, None, "share of hard cost",
                provenance="placeholder", evidence_tier="unresolved", interval_type="unavailable",
                limitations=["Hazard-specific site allowance is not supplied."])
            if hazard:
                hazard_envs.append(hazard)
        elif parcel.get(flag) is None:
            hazard_adjustments[flag] = _envelope(None, None, None, "share of hard cost",
                provenance="placeholder", evidence_tier="unresolved", interval_type="unavailable",
                limitations=["Parcel hazard flag is unknown; no adjustment applied."])
    effective_share = site_share
    if site_share and hazard_envs:
        effective_share = _derived_envelope(
            site_share["value"] + sum(h["value"] for h in hazard_envs),
            site_share["low"] + sum(h["low"] for h in hazard_envs),
            site_share["high"] + sum(h["high"] for h in hazard_envs),
            "share of hard cost", [site_share, *hazard_envs], evidence_tier="site_risk_scenario",
            interval_type="scenario_range", geography="parcel flag + Pittsburgh cost scenario",
            limitations=[
                "Flagged hazard reserves are declared budget scenarios without local engineering-cost calibration; they are not measured costs or evidence of required remediation."],
            confirmation="Obtain geotechnical review and contractor estimates for this parcel.")
    if site_rate:
        site = site_rate
    elif effective_share and hard_rate:
        site = _derived_envelope((hard["value"] * effective_share["value"]) if hard["value"] is not None else None,
            (hard["low"] * effective_share["low"]) if hard["low"] is not None else None,
            (hard["high"] * effective_share["high"]) if hard["high"] is not None else None,
            "USD", [hard, effective_share], evidence_tier=effective_share["evidence_tier"],
            interval_type=effective_share["interval_type"], geography=effective_share["geography"],
            limitations=list(effective_share["limitations"]),
            confirmation="Replace the declared site allowance with project engineering and utility quotes.")
    else:
        site = _envelope(None, None, None, "USD", provenance="placeholder", evidence_tier="unresolved",
            interval_type="unavailable", limitations=["Site work cost is not supplied; it is unknown, not zero."],
            confirmation="Obtain geotechnical, demolition, grading, and utility estimates.")
    soft_share = _resolved(defaults, ["soft_cost_share"], "share of hard cost")
    soft = _scale(soft_share, hard["value"] or 0, inputs=[hard]) if soft_share else _envelope(None, None, None, "USD",
        provenance="placeholder", evidence_tier="unresolved", interval_type="unavailable",
        limitations=["Soft costs are unknown until a project budget is supplied."])
    soft_low = (hard["low"] or 0) * soft_share["low"] if soft_share and hard["low"] is not None else None
    soft_high = (hard["high"] or 0) * soft_share["high"] if soft_share and hard["high"] is not None else None
    if soft_share:
        soft = _derived_envelope((hard["value"] * soft_share["value"]) if hard["value"] is not None else None,
            soft_low, soft_high, "USD", [hard, soft_share], evidence_tier="line_item_soft_cost_scenario",
            interval_type="scenario_range", geography=soft_share["geography"],
            limitations=["Soft-cost share is applied once to hard construction cost. HUD TDC is a benchmark and is not added as a separate line."],
            confirmation="Replace with a project sources-and-uses budget.")
    contingency_rate = _resolved(defaults, ["contingency_share"], "share of hard cost")
    contingency = _scale(contingency_rate, hard["value"] or 0, inputs=[hard]) if contingency_rate else _envelope(None, None, None, "USD",
        provenance="placeholder", evidence_tier="unresolved", interval_type="unavailable",
        limitations=["Contingency is unknown until a project budget is supplied."])
    if contingency_rate:
        contingency = _derived_envelope(
            (hard["value"] * contingency_rate["value"]) if hard["value"] is not None else None,
            (hard["low"] * contingency_rate["low"]) if hard["low"] is not None else None,
            (hard["high"] * contingency_rate["high"]) if hard["high"] is not None else None,
            "USD", [hard, contingency_rate], evidence_tier="line_item_contingency_scenario",
            geography="Pittsburgh cost scenario",
            confirmation="Replace with the project contingency line from a cost estimate.")
    # Site work, hard construction, soft costs, contingency and land are shown
    # as disjoint sources-and-uses lines. The HUD TDC figure is never a use.
    amounts = [hard, site, soft, contingency, land["value"]]
    def sum_key(key: str):
        vals = [x.get(key) for x in amounts]
        return sum(vals) if all(v is not None for v in vals) else None
    limitations = ["Illustrative scenario budget; no bid or parcel-specific construction quote is implied.",
                   "HUD HCC/TDC may be retained as a public-housing benchmark, but TDC is not added to these line items."]
    line_items = {"hard_construction": hard, "site_work": site, "soft_costs": soft,
                  "contingency": contingency, "land": land["value"]}
    result = {
        "line_items": line_items,
        "hazard_site_adjustments": hazard_adjustments,
        "total_uses": _derived_envelope(sum_key("value"), sum_key("low"), sum_key("high"), "USD",
            list(line_items.values()), evidence_tier="sources_and_uses_total",
            interval_type="scenario_range", geography="Pittsburgh scenario", limitations=limitations,
            confirmation="Replace scenario lines with project-specific sources-and-uses and title terms."),
        "per_unit_uses": _derived_envelope((sum_key("value") / units) if sum_key("value") is not None else None,
            (sum_key("low") / units) if sum_key("low") is not None else None,
            (sum_key("high") / units) if sum_key("high") is not None else None, "USD/unit",
            list(line_items.values()), evidence_tier="sources_and_uses_per_unit",
            interval_type="scenario_range", geography="Pittsburgh scenario", limitations=limitations),
        "hud_hcc_benchmark_per_unit": _assumption(defaults, "hud_hcc_benchmark_per_unit", unit="USD/unit"),
        "hud_tdc_benchmark_per_unit": _assumption(defaults, "hud_tdc_benchmark_per_unit", unit="USD/unit"),
    }
    return result


def _rental(cost: dict, units: int, defaults: dict) -> dict:
    total_uses = cost["total_uses"]
    uses_per_unit = cost["per_unit_uses"]
    debt_share = _assumption(defaults, "rental_debt_share", unit="share of uses")
    equity_share = _assumption(defaults, "rental_equity_share", unit="share of uses")
    subsidy_share = _assumption(defaults, "rental_subsidy_share", unit="share of uses")
    debt_rate = _assumption(defaults, "rental_debt_rate", unit="annual rate")
    debt_term = _assumption(defaults, "rental_debt_term_years", unit="years")
    equity_return = _assumption(defaults, "rental_equity_return_rate", unit="annual rate")
    opex_keys = ("taxes_per_unit_month", "insurance_per_unit_month", "utilities_per_unit_month",
                 "maintenance_per_unit_month", "management_per_unit_month", "reserves_per_unit_month")
    opex = {key.removesuffix("_per_unit_month"): _assumption(defaults, key, unit="USD/unit/month") for key in opex_keys}
    if opex.get("taxes") is None:
        tax_mills = _assumption(defaults, "property_tax_mills", unit="mills")
        if tax_mills and uses_per_unit["value"] is not None:
            opex["taxes"] = _derived_envelope(uses_per_unit["value"] * tax_mills["value"] / 1000 / 12,
                uses_per_unit["low"] * tax_mills["low"] / 1000 / 12 if uses_per_unit["low"] is not None else None,
                uses_per_unit["high"] * tax_mills["high"] / 1000 / 12 if uses_per_unit["high"] is not None else None,
                "USD/unit/month", [uses_per_unit, tax_mills], evidence_tier="assessed_value_cost_proxy",
                interval_type="scenario_range", geography="Pittsburgh",
                limitations=["Uses development cost as a proxy for post-build assessed value; actual assessment, abatements, exemptions, and classification may differ."],
                confirmation="Obtain post-build assessment estimate and applicable relief status.")
    opex_values = [v for v in opex.values() if v is not None]
    grossup = _resolved(defaults, ["vacancy_rate"], "share")
    coverage = _resolved(defaults, ["rental_dscr"], "ratio")
    shares = (debt_share, equity_share, subsidy_share)
    shares_complete = all(shares) and abs(sum(s["value"] for s in shares) - 1.0) <= 0.01
    if (total_uses["value"] is None or not shares_complete or not debt_rate or not debt_term
            or not equity_return or not coverage or len(opex_values) != len(opex) or not grossup):
        return {"operating_costs": opex,
            "funding_sources": {"debt": debt_share, "equity": equity_share, "subsidy": subsidy_share},
            "monthly_rent_required": _envelope(None, None, None, "USD/unit/month", provenance="placeholder",
                evidence_tier="unresolved", interval_type="unavailable",
                limitations=["Rental calculation requires debt/equity/subsidy shares summing to 100%, dated loan and equity terms, vacancy, and all operating-cost line items."],
                confirmation="Provide a project sources-and-uses plan, lender terms, subsidy eligibility/award status, and operating budget.")}
    dscr = coverage["value"] if coverage else 1.0
    uses_per = [uses_per_unit[k] for k in ("value", "low", "high")]
    op_mid = sum(x["value"] for x in opex_values)
    op_low = sum(x["low"] for x in opex_values)
    op_high = sum(x["high"] for x in opex_values)
    vac_mid = max(0, min(0.99, grossup["value"]))
    vac_low = max(0, min(0.99, grossup["low"]))
    vac_high = max(0, min(0.99, grossup["high"]))
    def annual_financing(use_per_unit: float, debt_pct: float, equity_pct: float,
                         loan_rate: float, loan_years: float, equity_yield: float) -> float:
        debt_payment = _payment(use_per_unit * debt_pct, loan_rate, round(loan_years * 12)) * 12
        equity_return_annual = use_per_unit * equity_pct * equity_yield
        return debt_payment * dscr + equity_return_annual
    vals = [((annual_financing(uses_per[0], debt_share["value"], equity_share["value"], debt_rate["value"], debt_term["value"], equity_return["value"]) / 12) + op_mid) / (1-vac_mid),
            ((annual_financing(uses_per[1], debt_share["low"], equity_share["low"], debt_rate["low"], debt_term["low"], equity_return["low"]) / 12) + op_low) / (1-vac_low),
            ((annual_financing(uses_per[2], debt_share["high"], equity_share["high"], debt_rate["high"], debt_term["high"], equity_return["high"]) / 12) + op_high) / (1-vac_high)]
    return {"operating_costs": opex,
        "funding_sources": {"debt": debt_share, "equity": equity_share, "subsidy": subsidy_share},
        "debt_rate": debt_rate, "debt_term_years": debt_term, "equity_return_rate": equity_return,
        "vacancy_rate": grossup, "dscr": coverage,
        "monthly_rent_required": _derived_envelope(vals[0], min(vals[1:]), max(vals[1:]), "USD/unit/month",
            [uses_per_unit, debt_share, equity_share, subsidy_share, debt_rate, debt_term,
             equity_return, grossup, coverage, *opex_values],
            evidence_tier="rental_sources_uses_screen", interval_type="scenario_range",
            geography="Pittsburgh rental scenario", limitations=["Debt is amortized at the declared rate/term; equity receives the declared annual return; DSCR applies to debt service. Subsidy lowers funded sources only when eligibility/award is explicitly represented in the source shares."],
            confirmation="Verify project debt, equity return, subsidy award, vacancy, and operating line items with the lender and operator.")}


def _payment(principal: float, annual_rate: float, months: int) -> float:
    monthly = annual_rate / 12
    if months <= 0:
        return 0.0
    if monthly == 0:
        return principal / months
    return principal * monthly / (1 - (1 + monthly) ** -months)


def _for_sale(cost: dict, defaults: dict) -> dict:
    # A declared break-even/target price is distinct from an observed home sale.
    price = _assumption(defaults, "for_sale_purchase_price", unit="USD/unit")
    price_type = "declared_price_input"
    if not price:
        margin = _assumption(defaults, "for_sale_margin_share", unit="share over required cost")
        uses = cost["per_unit_uses"]
        if margin and uses["value"] is not None:
            price = _derived_envelope(uses["value"] * (1 + margin["value"]),
                uses["low"] * (1 + margin["low"]) if uses["low"] is not None else None,
                uses["high"] * (1 + margin["high"]) if uses["high"] is not None else None,
                "USD/unit", [uses, margin], evidence_tier="break_even_target_price_scenario",
                interval_type="scenario_range", geography="Pittsburgh project scenario",
                limitations=[
                    "Target sale price is required line-item development uses plus a declared margin; it is not observed market value or an owner bid."],
                confirmation="Replace with a project sale-price policy and verify against new-home comparables and appraisal.")
            price_type = "break_even_target_price_scenario"
    if not price:
        missing = _envelope(None, None, None, "USD/unit", provenance="placeholder", evidence_tier="unresolved",
            interval_type="unavailable", limitations=["No line-item development cost or target margin supports a target price; assessed land value is used only as an acquisition-cost scenario and is not represented as a home sale price."],
            confirmation="Provide project line-item costs and a declared margin, or obtain new-home sales comparables.")
        return {"purchase_price": missing, "price_type": "unresolved", "actual_market_sale_price": missing,
            "buyer_monthly_cost": _envelope(None, None, None, "USD/unit/month",
            provenance="placeholder", evidence_tier="unresolved", interval_type="unavailable",
            limitations=["Ownership payment requires a supported purchase price and dated mortgage, tax, and insurance assumptions."])}
    down = _resolved(defaults, ["buyer_down_payment_share"], "share")
    mortgage = _resolved(defaults, ["buyer_mortgage_rate"], "annual rate")
    term = _resolved(defaults, ["buyer_mortgage_term_years"], "years")
    tax_rate = _resolved(defaults, ["property_tax_mills"], "mills")
    insurance = _resolved(defaults, ["buyer_insurance_per_unit_month"], "USD/unit/month")
    transfer = _resolved(defaults, ["transfer_tax_rate"], "share")
    if not all((down, mortgage, term, tax_rate)):
        monthly = _envelope(None, None, None, "USD/unit/month", provenance="placeholder",
            evidence_tier="unresolved", interval_type="unavailable",
            limitations=["Ownership calculation requires down payment, mortgage rate and term, property tax mills, and a target or observed home price."])
    else:
        months = round(term["value"] * 12)
        vals = []
        for p, d, r, tm in ((price["value"], down["value"], mortgage["value"], tax_rate["value"]),
                            (price["low"], down["high"], mortgage["low"], tax_rate["low"]),
                            (price["high"], down["low"], mortgage["high"], tax_rate["high"])):
            vals.append(_payment(p * (1-d), r, months) + p * tm / 1000 / 12)
        monthly = _derived_envelope(vals[0], min(vals[1:]), max(vals[1:]), "USD/unit/month",
            [price, down, mortgage, term, tax_rate], evidence_tier="buyer_payment_screen",
            interval_type="scenario_range", geography="Pittsburgh buyer scenario",
            limitations=["Includes principal, interest, and an assessed-value proxy using 2026 combined millage. Excludes homeowner insurance, HOA, utilities, maintenance, closing costs, and lender fees."],
            confirmation="Use a dated lender quote and parcel-specific post-build tax assessment.")
    insurance_monthly = insurance or _envelope(None, None, None, "USD/unit/month", provenance="placeholder",
        evidence_tier="unresolved", interval_type="unavailable",
        limitations=["No parcel-specific homeowner insurance quote supplied."], confirmation="Obtain an insurance quote.")
    transfer_result = None
    if transfer:
        transfer_result = _derived_envelope(
            (transfer["value"] * price["value"]) if price["value"] is not None else None,
            (transfer["low"] * price["low"]) if price["low"] is not None else None,
            (transfer["high"] * price["high"]) if price["high"] is not None else None,
            "USD/unit", [transfer, price], evidence_tier=transfer["evidence_tier"],
            interval_type="price_and_transfer_rate_range", geography=transfer["geography"],
            limitations=["Gross transfer tax is shown separately from mortgage payments; actual payer allocation depends on sale terms."])
    return {"purchase_price": price, "price_type": price_type, "actual_market_sale_price": _envelope(None, None, None,
                "USD/unit", provenance="placeholder", evidence_tier="unresolved", interval_type="unavailable",
                limitations=["New-home market sale comparables are not present in the vacant-land sales input."],
                confirmation="Load licensed, validated new-home sale comparables before describing market value."),
            "buyer_monthly_cost": monthly, "buyer_insurance_per_unit_month": insurance_monthly,
            "transfer_tax_gross": transfer_result, "property_tax_mills": tax_rate}


FINANCE_SOURCE_URLS = {
    "hud_hcc": "https://www.hud.gov/sites/dfiles/PIH/documents/2024_Units_TDC_Limits.pdf",
    "phfa_budget": "https://www.phfa.org/forms/multifamily_application_guidelines/submission/tab_02/tab_02_01.pdf",
    "phfa_application": "https://www.phfa.org/forms/multifamily_application_guidelines/submission/tab_02/tab_02_02.pdf",
    "tax_rates": "https://apps.alleghenycounty.us/website/munipgh.asp",
    "city_transfer": "https://www.pittsburghpa.gov/City-Government/Finance-Budget/Taxes",
    "county_transfer": "https://www.alleghenycounty.us/Services/Property-Assessments-and-Real-Estate/Realty-Transfer-Taxes",
    "pmms": "https://www.freddiemac.com/pmms/pmms_archives",
    "pwsa_rates": "https://www.pgh2o.com/residential-commercial-customers/rates",
}


def _cfg_range(cfg: Any, assumption_key: str, typology_id: str) -> dict | None:
    assumptions = cfg.get("assumptions", {}) if isinstance(cfg, dict) else getattr(cfg, "assumptions", {})
    raw = assumptions.get(assumption_key) if isinstance(assumptions, dict) else None
    if raw is None:
        return None
    if hasattr(raw, "model_dump"):
        raw = raw.model_dump()
    if not isinstance(raw, dict):
        return None
    selected = (raw.get("by_typology") or {}).get(typology_id, raw)
    if hasattr(selected, "model_dump"):
        selected = selected.model_dump()
    if not isinstance(selected, dict):
        return None
    source_id = raw.get("source")
    return {k: selected[k] for k in ("value", "low", "high") if k in selected} | {
        "unit": raw.get("unit", "USD"), "provenance": raw.get("provenance", "assumption"),
        "source_ids": [source_id] if source_id else [],
        "limitations": [raw.get("rationale", "Configured scenario input.")],
    }


def _config_sources(cfg: Any) -> dict[str, Any]:
    if isinstance(cfg, dict):
        sources = cfg.get("sources", {})
        return sources.get("sources", {}) if isinstance(sources, dict) else {}
    sources = getattr(cfg, "sources", None)
    return getattr(sources, "sources", {}) if sources is not None else {}


def _source_id(cfg: Any, *, url: str | None = None, name: str | None = None) -> str | None:
    for source_id, raw in _config_sources(cfg).items():
        item = raw.model_dump() if hasattr(raw, "model_dump") else raw
        if not isinstance(item, dict):
            continue
        if url is not None and item.get("url") == url:
            return source_id
        if name is not None and item.get("name") == name:
            return source_id
    return None


def _source_refs(cfg: Any) -> dict[str, dict]:
    selected = {}
    for url in FINANCE_SOURCE_URLS.values():
        source_id = _source_id(cfg, url=url)
        if source_id is None:
            continue
        raw = _config_sources(cfg)[source_id]
        item = raw.model_dump() if hasattr(raw, "model_dump") else raw
        selected[source_id] = {k: item.get(k) for k in ("name", "publisher", "url", "vintage", "verified")}
    scenario_id = _source_id(cfg, name="Lotline declared planning scenario")
    if scenario_id is not None:
        raw = _config_sources(cfg)[scenario_id]
        item = raw.model_dump() if hasattr(raw, "model_dump") else raw
        selected[scenario_id] = {k: item.get(k) for k in ("name", "publisher", "url", "vintage", "verified")}
    return selected


def _assessment_source(cfg: Any) -> str | None:
    if isinstance(cfg, dict):
        city = cfg.get("city", {})
        parcels = city.get("parcels", {}) if isinstance(city, dict) else {}
        return parcels.get("assessments_source") if isinstance(parcels, dict) else None
    return getattr(cfg, "assessment_source", None)


def build_finance_defaults(cfg: Any, typology_id: str) -> dict:
    """Build dated finance scenarios from configured typology plus official references.

    Public HCC is supplied as a construction-cost *scenario benchmark*, not a
    project bid. The old TDC-minus-HCC gap is intentionally never converted to
    a soft-cost allowance. Unavailable project quotes and rental loan terms stay
    unresolved; source-derived reference figures are not silently applied to
    the wrong geography, tenure, or utility usage.
    """
    today = datetime.now(UTC).date().isoformat()
    hcc = _cfg_range(cfg, "hard_cost_psf", typology_id)
    if hcc:
        hcc.update({"unit": "USD/sf", "evidence_tier": "public_hcc_limit_scenario",
                    "interval_type": "scenario_range", "geography": "Pittsburgh HUD HCC typology proxy",
                    "source_snapshot_ids": ["2024"],
                    "as_of": today, "model_id": None, "model_version": None, "sample_size": None,
                    "limitations": ["HUD HCC is a public-housing construction-cost limit, not a local contractor bid; configured escalations/typology mapping are assumptions."],
                    "confirmation_needed": "Replace with a project-specific contractor estimate."})
    else:
        hcc = None

    typologies = cfg.get("typologies", []) if isinstance(cfg, dict) else getattr(cfg, "typologies", [])
    typology = next((t.model_dump() if hasattr(t, "model_dump") else t for t in typologies
                     if (t.get("id") if isinstance(t, dict) else getattr(t, "id", None)) == typology_id), {})
    unit_size = _finite(typology.get("unit_size_sf")) if isinstance(typology, dict) else None
    hcc_per_unit = _scale(_assumption({"hcc": hcc}, "hcc", unit="USD/sf"), unit_size) if hcc and unit_size else None
    tdc_multiplier = _cfg_range(cfg, "hud_tdc_multiplier", typology_id)
    tdc_per_unit = _scale(_assumption({"tdc_multiplier": tdc_multiplier}, "tdc_multiplier", unit="TDC/HCC"),
                          hcc_per_unit["value"], "USD/unit", inputs=[hcc_per_unit]) if hcc_per_unit and tdc_multiplier else None
    if tdc_per_unit:
        tdc_per_unit["limitations"] = ["HUD published TDC-to-HCC limit multiplier used only as a separate benchmark; it is not added to line items or reused as a soft-cost share."]

    scenario_source_id = (_source_id(cfg, name="Lotline Declared Finance Scenario Defaults")
                          or _source_id(cfg, name="Lotline declared planning scenario"))

    def source_id_for(role):
        url = FINANCE_SOURCE_URLS.get(role)
        return _source_id(cfg, url=url) if url else scenario_source_id

    def source_ids_for(role):
        source_id = source_id_for(role)
        return [source_id] if source_id else []

    def scenario(value, low, high, unit, source, limitations, *, source_vintage=None, provenance="assumption"):
        refs = source_ids_for(source)
        return {"value": value, "low": low, "high": high, "unit": unit,
                "provenance": provenance, "evidence_tier": "declared_scenario",
                "interval_type": "scenario_range", "geography": "Pittsburgh planning scenario",
                "source_ids": refs, "source_snapshot_ids": [source_vintage or today] if refs else [],
                "model_id": None, "model_version": None, "sample_size": None, "as_of": today,
                "limitations": limitations, "confirmation_needed": "Replace with project-specific quotes and approved sources-and-uses."}

    def ref(role):
        return source_ids_for(role)

    defaults = {
        "analysis_date": today,
        "hard_cost_psf": hcc,
        "hud_hcc_benchmark_per_unit": hcc_per_unit,
        "hud_tdc_benchmark_per_unit": tdc_per_unit,
        # These are Lotline declared allowances, not derived from HUD TDC/HCC.
        "soft_cost_share": scenario(.25, .15, .40, "share of hard cost", "scenario",
            ["Declared allowance for design, permits, insurance, and project financing; not estimated from HUD TDC and not calibrated to local budgets."]),
        "site_cost_share": scenario(.10, 0, .25, "share of hard cost", "scenario",
            ["Broad undeveloped site-work scenario only; actual parcel geotechnical, demolition, grading, and connection costs are unknown."]),
        "contingency_share": scenario(.10, .05, .15, "share of hard cost", "scenario",
            ["Declared construction contingency scenario; not a local observed cost distribution."]),
        "for_sale_margin_share": scenario(.10, 0, .20, "share over required cost", "scenario",
            ["Declared break-even/target sale margin scenario. A target price is line-item cost plus this margin, not an observed market price."]),
        "buyer_down_payment_share": scenario(.20, .10, .30, "share", "scenario",
            ["Illustrative buyer down-payment scenario; actual loan eligibility and down payment vary."]),
        "buyer_mortgage_term_years": scenario(30, 30, 30, "years", "scenario",
            ["Illustrative 30-year fixed mortgage term; obtain lender terms." ]),
        "buyer_mortgage_rate": {"value": .0703, "low": .0676, "high": .0703, "unit": "annual rate",
            "provenance": "observed", "evidence_tier": "national_mortgage_rate_reference",
            "interval_type": "recent_weekly_rate_range", "geography": "United States",
            "source_ids": ref("pmms"), "source_snapshot_ids": ["2026-09-10", "2026-09-24"],
            "as_of": "2026-09-24", "model_id": None, "model_version": None, "sample_size": None,
            "limitations": ["National PMMS 30-year fixed averages (6.76% to 7.03%); not a borrower quote or Pittsburgh-specific offer."],
            "confirmation_needed": "Replace with a dated borrower-specific lender quote."},
        "rental_debt_share": scenario(.70, .70, .70, "share of uses", "scenario",
            ["Declared illustrative sources-and-uses split; no project loan commitment is evidenced."]),
        "rental_equity_share": scenario(.30, .30, .30, "share of uses", "scenario",
            ["Declared illustrative sources-and-uses split; no equity commitment is evidenced."]),
        "rental_subsidy_share": scenario(0, 0, 0, "share of uses", "scenario",
            ["Base scenario assumes no subsidy award. This does not mean the project is ineligible or that assistance is unavailable."]),
        "rental_debt_rate": scenario(.075, .065, .085, "annual rate", "scenario",
            ["Illustrative multifamily debt-rate range; Freddie Mac PMMS single-family rates are not substituted for a multifamily loan quote."]),
        "rental_debt_term_years": scenario(30, 25, 35, "years", "scenario",
            ["Illustrative amortization term; actual loan amortization and maturity are lender-specific."]),
        "rental_equity_return_rate": scenario(.05, .03, .07, "annual rate", "scenario",
            ["Illustrative annual equity cash return; no investor term sheet is available."]),
        "insurance_per_unit_month": scenario(125, 75, 200, "USD/unit/month", "scenario",
            ["Illustrative multifamily insurance allowance; PHFA requires project insurance quotes and buffers them in underwriting."]),
        "utilities_per_unit_month": scenario(159.40, 115.29, 250, "USD/unit/month", "pwsa_rates",
            ["Illustrative owner-paid utility scenario. PWSA publishes a $159.40 single-family sample bill at 3,000 gallons and one ERU; range endpoints are Lotline stress assumptions, not observed multifamily bills."], source_vintage="2026-03-08"),
        "maintenance_per_unit_month": scenario(150, 100, 250, "USD/unit/month", "scenario",
            ["Illustrative operations and maintenance allowance, not a local cost observation."]),
        "management_per_unit_month": scenario(100, 75, 150, "USD/unit/month", "scenario",
            ["Illustrative management allowance, not a management quote or PHFA cost observation."]),
        "reserves_per_unit_month": {"value": 500/12, "low": 500/12, "high": 500/12,
            "unit": "USD/unit/month", "provenance": "assumption", "evidence_tier": "program_minimum_reference",
            "interval_type": "reference_scenario", "geography": "PHFA general/family multifamily program",
            "source_ids": ref("phfa_budget"), "source_snapshot_ids": ["2025"], "as_of": today,
            "model_id": None, "model_version": None, "sample_size": None,
            "limitations": ["PHFA instructions state $500/unit/year for general or family proposals; program-specific reserve reference, not a universal actual operating cost."],
            "confirmation_needed": "Verify required reserve for the selected funding program."},
        "property_tax_mills": {"value": 26.557, "low": 26.557, "high": 26.557, "unit": "mills",
            "provenance": "observed", "evidence_tier": "published_2026_tax_rates",
            "interval_type": "fixed_published_rate", "geography": "City of Pittsburgh + Pittsburgh School District + Allegheny County",
            "source_ids": ref("tax_rates"), "source_snapshot_ids": ["2026"], "as_of": "2026-09-27",
            "model_id": None, "model_version": None, "sample_size": None,
            "limitations": ["26.557 mills = 9.670 City + 10.457 School + 6.430 County. Post-build taxable assessment, abatements, and exemptions are not known."],
            "confirmation_needed": "Confirm effective millage and post-build assessed value for the parcel."},
        "transfer_tax_rates": [
            {"value": .04, "low": .04, "high": .04, "unit": "share", "provenance": "observed",
             "evidence_tier": "published_source_component_total", "interval_type": "source_value",
             "geography": "City of Pittsburgh", "source_ids": ref("city_transfer"),
             "source_snapshot_ids": ["2026-03-05"], "as_of": "2026-03-05",
             "limitations": ["City page currently lists City 2%, School 1%, State 1% components, totaling 4%."],
             "confirmation_needed": "Confirm applicable local transfer taxes with the closing agent."},
            {"value": .05, "low": .05, "high": .05, "unit": "share", "provenance": "observed",
             "evidence_tier": "published_source_total", "interval_type": "source_value",
             "geography": "City of Pittsburgh", "source_ids": ref("county_transfer"),
             "source_snapshot_ids": ["2026-09-27"], "as_of": "2026-09-27",
             "limitations": ["County page states Pittsburgh total 5% and gives a 5% example."],
             "confirmation_needed": "Resolve source discrepancy and confirm payer allocation."},
        ],
        # PHFA references are exposed but only the 5% vacancy and 1.15 DSCR
        # sample/underwriting values are used. Other unit costs need a budget.
        "vacancy_rate": {"value": .05, "low": .05, "high": .05, "unit": "share",
            "provenance": "assumption", "evidence_tier": "published_sample_budget_reference",
            "interval_type": "reference_scenario", "geography": "PHFA multifamily application example",
            "source_ids": ref("phfa_application"), "source_snapshot_ids": ["2025"], "as_of": today,
            "model_id": None, "model_version": None, "sample_size": None,
            "limitations": ["5% residential vacancy is in PHFA's sample operating budget, not a Pittsburgh vacancy observation or requirement."],
            "confirmation_needed": "Replace with a project market study and lender underwriting."},
        "rental_dscr": {"value": 1.15, "low": 1.15, "high": 1.15, "unit": "ratio",
            "provenance": "assumption", "evidence_tier": "published_underwriting_reference",
            "interval_type": "reference_scenario", "geography": "PHFA multifamily underwriting",
            "source_ids": ref("phfa_budget"), "source_snapshot_ids": ["2025"], "as_of": today,
            "model_id": None, "model_version": None, "sample_size": None,
            "limitations": ["PHFA operating instructions describe 115% DSCR for its primary debt-service calculation; not a universal lender term."],
            "confirmation_needed": "Use the selected lender's debt coverage requirement."},
        "phfa_replacement_reserve_per_unit_month": {"value": 500/12, "low": 500/12, "high": 500/12,
            "unit": "USD/unit/month", "provenance": "observed", "evidence_tier": "program_minimum_reference",
            "interval_type": "fixed_program_reference", "geography": "PHFA general/family multifamily program",
            "source_ids": ref("phfa_budget"), "source_snapshot_ids": ["2025"], "as_of": today,
            "model_id": None, "model_version": None, "sample_size": None,
            "limitations": ["PHFA instructions state $500/unit/year for general or family proposals; program-specific reserve, not a universal actual operating cost."],
            "confirmation_needed": "Verify required reserve for the selected funding program."},
        "pwsa_reference_bill": {"value": 159.40, "low": 159.40, "high": 159.40,
            "unit": "USD/household/month", "provenance": "observed", "evidence_tier": "published_tariff_example",
            "interval_type": "example_bill", "geography": "Pittsburgh Water residential example",
            "source_ids": ref("pwsa_rates"), "source_snapshot_ids": ["2026-03-08"], "as_of": today,
            "model_id": None, "model_version": None, "sample_size": None,
            "limitations": ["Published example: single-family, 5/8-inch meter, 3,000 gallons/month, one ERU stormwater, including ALCOSAN; not a multifamily per-unit forecast."],
            "confirmation_needed": "Model actual metering, occupancy, impervious area, and owner/tenant-paid utilities."},
        "assessment_source": _assessment_source(cfg),
        "finance_source_refs": _source_refs(cfg),
    }
    for flag, key in (("steep_slope", "steep_slope_cost_share"),
                      ("landslide", "landslide_cost_share"),
                      ("undermined", "undermined_cost_share")):
        hazard = _cfg_range(cfg, key, typology_id)
        if hazard:
            hazard.update({"unit": "share of hard cost",
                "evidence_tier": "declared_site_risk_reserve", "interval_type": "budget stress scenario range",
                "geography": "parcel hazard flag plus declared budget reserve",
                "source_snapshot_ids": ["2025 PHFA reference; Lotline reserve model v1"],
                "as_of": "2026-09-27", "model_id": "lotline:declared-planning-budget:v1",
                "model_version": "1", "sample_size": None,
                "confirmation_needed": "Get parcel-specific geotechnical and contractor estimates."})
        defaults[key] = hazard
    return defaults


def estimate_finance(parcel: dict, typology_id: str, units: int, unit_size_sf: float,
                     evidence: dict, defaults: dict) -> dict:
    """Estimate land value and separate rental/ownership screening scenarios.

    Args use normalized mappings so the offline sales loader can pass candidate
    comps once per parcel. Tax and financing inputs must carry dated source
    metadata in ``defaults``; incomplete outputs stay null rather than defaulting
    to zero. ``defaults['transfer_tax_rates']`` may provide the documented 4%
    City and 5% County alternatives; these are returned as a conflict range.
    """
    if units <= 0 or unit_size_sf <= 0:
        raise ValueError("units and unit_size_sf must be positive")
    today = _date(defaults.get("analysis_date")) or datetime.now(UTC).date()
    land = _land_value(parcel, evidence, defaults, today)
    cost = _development_cost(units * unit_size_sf, units, land, defaults, parcel)
    rental = _rental(cost, units, defaults)
    for_sale = _for_sale(cost, defaults)
    alternatives = defaults.get("transfer_tax_rates")
    if alternatives:
        rates = [_assumption({"transfer": item}, "transfer", unit="share") for item in alternatives]
        rates = [r for r in rates if r]
        price = for_sale.get("purchase_price")
        if rates and price and price["value"] is not None:
            rate_min, rate_max = min(r["low"] for r in rates), max(r["high"] for r in rates)
            rate_mid = (rate_min + rate_max) / 2
            conflicted = _envelope(rate_mid, rate_min, rate_max, "share", provenance="observed",
                evidence_tier="conflicting_sources", interval_type="source_conflict_range", geography="Pittsburgh",
                source_ids=sorted({s for r in rates for s in r["source_ids"]}),
                snapshots=sorted({s for r in rates for s in r["source_snapshot_ids"]}),
                as_of=max((r["as_of"] for r in rates if r["as_of"]), default=None),
                limitations=["Published City and County documentation conflict: 4% versus 5%; retained as a range pending source review."],
                confirmation="Confirm applicable tax, exemptions, and payer allocation with the closing agent.")
            for_sale["transfer_tax_rate_conflict"] = conflicted
            for_sale["transfer_tax_gross"] = _derived_envelope(
                price["value"] * rate_mid,
                price["low"] * rate_min,
                price["high"] * rate_max,
                "USD/unit", [price, conflicted], evidence_tier="conflicting_sources",
                interval_type="combined_price_and_source_conflict_range", geography="Pittsburgh",
                limitations=["Gross transaction-tax range combines the 4%–5% published rate conflict with the declared purchase-price range; payer allocation depends on sale terms."],
                confirmation="Confirm applicable tax, exemptions, and payer allocation with the closing agent.")
    return {"typology_id": typology_id, "units": units, "unit_size_sf": unit_size_sf,
            "land_value": land, "development_cost": cost, "rental": rental, "for_sale": for_sale,
            "scenario_source_refs": defaults.get("finance_source_refs", {})}
