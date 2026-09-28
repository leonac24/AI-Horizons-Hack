"""Evidence-bounded environmental scenario calculations for Lotline.

This module is deliberately dependency-light and contains no parcel-capacity
inference. It combines supplied source envelopes and declared scenario inputs;
it never turns a nearby sewershed or tract average into a parcel observation.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any


def estimate_environment(
    parcel: dict,
    typology_id: str,
    units: int,
    unit_size_sf: float,
    evidence: dict,
    defaults: dict,
) -> dict:
    """Return environmental scenario envelopes for one parcel/typology.

    ``evidence`` accepts values in the standard evidence-envelope form
    (``value``, ``low``, ``high``, ``unit``, ``provenance`` and provenance
    metadata). ``defaults`` accepts the same shape, or the existing config
    assumption shape with ``by_typology``. Missing inputs stay null.
    """
    evid = evidence if isinstance(evidence, dict) else {}
    cfg = defaults if isinstance(defaults, dict) else {}

    embodied = _input(evid, cfg, "embodied_kgco2e_psf", typology_id,
                      "kgCO2e/sf", "declared_material_quantity_scenario")
    energy = _input(evid, cfg, "operational_kwh_psf_yr", typology_id,
                    "kWh/sf/yr", "building_energy_scenario")
    travel = _input(evid, cfg, "vmt_per_household_yr", typology_id,
                    "miles/household/yr", "household_travel_scenario")
    annual_travel_input = travel if travel and _is_annual_travel(travel.get("unit", "")) else None
    grid = _input(evid, cfg, "grid_kgco2e_per_kwh", typology_id,
                  "kgCO2e/kWh", "regional_grid_scenario")
    grid_path = _input(evid, cfg, "grid_kgco2e_by_year", typology_id,
                       "kgCO2e/kWh by year", "regional_grid_scenario")
    grid_decarbonization = _input(evid, cfg, "grid_decarbonization_per_yr", typology_id,
                                 "share/year", "regional_grid_scenario")
    vehicle = _input(evid, cfg, "kgco2e_per_vmt", typology_id,
                     "kgCO2e/mile", "vehicle_emissions_scenario")
    sewer_context = _lookup(evid, "sewer_overflow_context")

    area = _number(units) * _number(unit_size_sf)
    embodied_total = _scale(embodied, area, "kgCO2e", "whole_scenario")
    annual_energy = _scale(energy, area, "kWh/yr", "whole_scenario")
    annual_travel = _scale(annual_travel_input, _number(units), "miles/yr", "whole_scenario")

    flow_per_home = _input(evid, cfg, "wastewater_gpd_per_home", typology_id,
                           "gallons/home/day", "wastewater_design_flow_scenario")
    if flow_per_home is None:
        occupants = _input(evid, cfg, "occupants_per_home", typology_id,
                           "persons/home", "wastewater_design_flow_scenario")
        flow_person = _input(evid, cfg, "wastewater_gpd_per_person", typology_id,
                             "gallons/person/day", "wastewater_design_flow_scenario")
        flow_per_home = _multiply(occupants, flow_person, "gallons/home/day",
                                  "wastewater_design_flow_scenario")
    added_flow = _scale(flow_per_home, _number(units), "gallons/day", "whole_scenario")
    if added_flow:
        added_flow["limitations"] = _merge_text(
            added_flow.get("limitations"),
            "Planning-level added design flow only; not a measured discharge or pipe-capacity finding.",
        )
        added_flow["confirmation_needed"] = "PWSA/ALCOSAN sewer availability and capacity review"
        added_flow["geography"] = "proposed scenario"

    outputs: dict[str, Any] = {
        "embodied_kgco2e_psf": embodied,
        "embodied_kgco2e_scenario": embodied_total,
        "operational_kwh_psf_yr": energy,
        "operational_kwh_scenario_yr": annual_energy,
        "vmt_per_household_yr": travel,
        "vmt_scenario_yr": annual_travel,
        "wastewater_occupants_per_home": _input(
            evid, cfg, "occupants_per_home", typology_id, "persons/home", "declared_occupancy_scenario"
        ),
        "grid_kgco2e_per_kwh": grid,
        "grid_kgco2e_by_year": grid_path,
        "wastewater_added_gpd": added_flow,
        "sewer_overflow_context": _context_envelope(sewer_context),
    }
    outputs["carbon_scenario"] = _carbon_scenario(
        _scale(embodied, _number(unit_size_sf), "kgCO2e/home", "typology scenario"),
        _scale(energy, _number(unit_size_sf), "kWh/home/yr", "typology scenario"),
        annual_travel_input, grid, grid_path, vehicle, cfg.get("analysis_years", 60),
        grid_decarbonization, cfg.get("analysis_start_year"),
    )
    inputs = {
        "embodied_kgco2e_psf": embodied,
        "operational_kwh_psf_yr": energy,
        "vmt_per_household_yr": travel,
        "kgco2e_per_vmt": vehicle,
    }
    if grid_path:
        inputs["grid_kgco2e_by_year"] = grid_path
    else:
        inputs["grid_kgco2e_per_kwh"] = grid
        if grid_decarbonization:
            inputs["grid_decarbonization_per_yr"] = grid_decarbonization
    outputs["carbon_scenario"]["inputs"] = {key: value for key, value in inputs.items() if value}
    # Parcel linkage is included for provenance, but no sewer capacity field is
    # synthesized from sewershed membership or overflow history.
    outputs["sewer_capacity"] = {
        "value": None, "low": None, "high": None, "unit": "unknown",
        "provenance": "placeholder", "evidence_tier": "unresolved_confirmation",
        "interval_type": "none", "geography": _sewer_geography(parcel),
        "source_ids": [], "as_of": None,
        "limitations": "Mapped sewershed and historical overflow context do not establish available capacity.",
        "confirmation_needed": "Written PWSA/ALCOSAN capacity or availability determination",
    }
    return outputs


def environment_defaults_from_config(cfg: Any, typology_id: str) -> dict:
    """Extract only non-placeholder defaults that name a configured source.

    These are cited scenario inputs, not parcel observations. Uncited config
    placeholders are omitted so callers cannot accidentally promote them.
    """
    keys = (
        "embodied_kgco2e_psf", "operational_kwh_psf_yr", "vmt_per_household_yr",
        "grid_kgco2e_per_kwh", "grid_decarbonization_per_yr", "kgco2e_per_vmt",
        "wastewater_gpd_per_home", "wastewater_gpd_per_person", "occupants_per_home",
    )
    source_catalog = getattr(getattr(cfg, "sources", None), "sources", {})
    result: dict[str, Any] = {}
    for key in keys:
        try:
            assumption = cfg.assumption(key)
        except (KeyError, AttributeError):
            continue
        source = getattr(assumption, "source", None)
        provenance = getattr(assumption, "provenance", "placeholder")
        if not source or source not in source_catalog or provenance == "placeholder":
            continue
        band = assumption.for_typology(typology_id) if hasattr(assumption, "for_typology") else assumption
        result[key] = {
            "value": band.value, "low": band.low, "high": band.high,
            "unit": assumption.unit, "provenance": provenance,
            "evidence_tier": "cited_scenario_input", "interval_type": "scenario_range",
            "geography": "regional or typology scenario; not parcel observation",
            "source_ids": [source], "as_of": None,
            "limitations": assumption.rationale,
        }
    try:
        analysis_years = cfg.assumption("analysis_years").value
    except (KeyError, AttributeError):
        analysis_years = 60
    result["analysis_years"] = int(analysis_years)
    dep_flow_source = next((
        source_id for source_id, source in source_catalog.items()
        if "domestic wastewater facilities manual" in str(getattr(source, "name", "")).casefold()
    ), None)
    if dep_flow_source:
        result["wastewater_gpd_per_person"] = {
            "value": 100, "low": 100, "high": 100,
            "unit": "gallons/person/day", "provenance": "assumption",
            "evidence_tier": "cited_design_reference", "interval_type": "point_reference",
            "geography": "planning-level reference for a proposed residential scenario",
            "source_ids": [dep_flow_source], "as_of": None,
            "limitations": "PA DEP Domestic Wastewater Facilities Manual §24.1 p.22: new sewer systems use at least 100 gpd/person for average daily design flow unless rigorously justified; includes normal infiltration. This is a design reference, not measured household discharge.",
            "confirmation_needed": "Confirm applicable design-flow basis with PA DEP/PWSA/ALCOSAN for the project",
        }
        result["occupants_per_home"] = {
            "value": 2, "low": 1, "high": 4,
            "unit": "persons/home", "provenance": "assumption",
            "evidence_tier": "declared_scenario", "interval_type": "scenario_range",
            "geography": "housing scenario",
            "source_ids": [], "model_id": "declared_occupancy_scenario", "as_of": None,
            "limitations": "Declared planning range of 1–4 occupants per home, centered at 2; not a household count or prediction.",
            "confirmation_needed": "Replace with the proposal's documented occupancy/program assumptions",
        }
    return result


def _input(evidence: dict, defaults: dict, key: str, typology: str,
           unit: str, fallback_model: str) -> dict | None:
    value = _lookup(evidence, key, typology)
    if value is not None:
        return _normalize(value, unit)
    value = _lookup(defaults, key, typology)
    if value is None:
        return None
    cited = isinstance(value, Mapping) and bool(
        value.get("source_ids") or value.get("sourceIds") or value.get("source") or value.get("model_id")
    )
    if not cited:
        return None
    has_provenance = isinstance(value, Mapping) and bool(value.get("provenance"))
    envelope = _normalize(value, unit)
    if not has_provenance:
        envelope["provenance"] = "placeholder"
    envelope.setdefault("evidence_tier", "declared_scenario")
    envelope.setdefault("interval_type", "scenario_range")
    envelope.setdefault("geography", "regional or typology scenario; not parcel observation")
    envelope.setdefault("source_ids", [])
    envelope.setdefault("model_id", fallback_model)
    if not envelope.get("limitations"):
        envelope["limitations"] = _merge_text(
            envelope.get("rationale"), "Declared scenario input; it is not a parcel observation."
        )
    return envelope


def _lookup(mapping: dict, key: str, typology: str | None = None) -> Any:
    value = mapping.get(key)
    if value is None:
        return None
    if typology and isinstance(value, Mapping):
        by_typology = value.get("by_typology")
        if isinstance(by_typology, Mapping):
            if typology in by_typology:
                return {**value, **by_typology[typology]}
            if not value.get("generic_typology_fallback_declared"):
                return None
        if typology in value and isinstance(value[typology], Mapping):
            return {**value, **value[typology]}
    return value


def _normalize(value: Any, unit: str) -> dict:
    if isinstance(value, Mapping):
        result = dict(value)
    else:
        result = {"value": value, "low": value, "high": value}
    for key in ("value", "low", "high"):
        if key not in result and "value" in result:
            result[key] = result["value"]
    result.setdefault("unit", unit)
    result.setdefault("provenance", "modeled")
    result.setdefault("evidence_tier", "scenario")
    result.setdefault("interval_type", "scenario_range" if result.get("low") != result.get("high") else "point")
    result.setdefault("geography", "not specified")
    legacy_sources = result.pop("sourceIds", None)
    if "source_ids" not in result:
        source = result.get("source")
        result["source_ids"] = legacy_sources or ([source] if source else [])
    result.setdefault("as_of", None)
    result.setdefault("limitations", "")
    result.setdefault("confirmation_needed", None)
    return result


def _scale(envelope: dict | None, factor: float, unit: str, geography: str) -> dict | None:
    if envelope is None or _number(envelope.get("value"), None) is None:
        return None
    out = dict(envelope)
    for key in ("value", "low", "high"):
        val = _number(envelope.get(key), None)
        out[key] = None if val is None else val * factor
    out["unit"] = unit
    out["geography"] = geography
    return out


def _multiply(left: dict | None, right: dict | None, unit: str, model_id: str) -> dict | None:
    if left is None or right is None:
        return None
    a = tuple(_number(left.get(k), None) for k in ("value", "low", "high"))
    b = tuple(_number(right.get(k), None) for k in ("value", "low", "high"))
    if any(v is None for v in (*a, *b)):
        return None
    low, high = min(a[1] * b[1], a[1] * b[2], a[2] * b[1], a[2] * b[2]), max(a[1] * b[1], a[1] * b[2], a[2] * b[1], a[2] * b[2])
    return {
        "value": a[0] * b[0], "low": low, "high": high, "unit": unit,
        "provenance": "assumption" if "assumption" in (left.get("provenance"), right.get("provenance")) else "modeled",
        "evidence_tier": "declared_scenario", "interval_type": "scenario_range",
        "geography": "scenario", "source_ids": sorted(set(left.get("source_ids", [])) | set(right.get("source_ids", []))),
        "as_of": None, "model_id": model_id,
        "limitations": _merge_text(left.get("limitations"), right.get("limitations")),
        "confirmation_needed": None,
    }


def _carbon_scenario(embodied: dict | None, energy: dict | None, travel: dict | None,
                     grid: dict | None, grid_path: dict | None, vehicle: dict | None,
                     years: Any, decarbonization: dict | None, start_year: Any) -> dict:
    count = max(1, int(_number(years, 60)))
    trajectory_years = ([int(year) for year in grid_path.get("years", [])]
                        if grid_path and grid_path.get("years") else None)
    base_year = int(_number(start_year, datetime.now(UTC).year))
    if embodied is None or energy is None or travel is None or vehicle is None or (grid is None and grid_path is None):
        return {"value": None, "low": None, "high": None, "unit": "kgCO2e/home over analysis period",
                "provenance": "placeholder", "evidence_tier": "unresolved_inputs", "interval_type": "none",
                "geography": "scenario", "source_ids": [], "as_of": None,
                "limitations": "A total is withheld because one or more energy, travel, material, grid, or vehicle inputs are unavailable.",
                "confirmation_needed": None, "analysis_years": count}
    grid_values = grid_path.get("value") if grid_path else None
    usable_trajectory = isinstance(grid_values, list) and any(_number(value, None) is not None for value in grid_values)
    if not usable_trajectory and grid is None:
        return {"value": None, "low": None, "high": None, "unit": "kgCO2e/home over analysis period",
                "provenance": "placeholder", "evidence_tier": "unresolved_inputs", "interval_type": "none",
                "geography": "scenario", "source_ids": [], "as_of": None,
                "limitations": "Grid input has no usable annual values; a carbon total is withheld.",
                "confirmation_needed": None, "analysis_years": count}
    # A supplied grid trajectory is a sequence of annual emissions factors.
    def annual_grid(year_index: int) -> tuple[float, float, float]:
        if usable_trajectory:
            target_year = base_year + year_index
            eligible = [i for i, year in enumerate(trajectory_years or []) if _number(year, None) is not None and int(year) <= target_year]
            index = eligible[-1] if eligible else 0
            if not trajectory_years:
                index = min(year_index, len(grid_values) - 1)
            index = min(index, len(grid_values) - 1)
            v = _number(grid_values[index], None)
            if v is None:
                raise ValueError("annual grid trajectory contains a nonnumeric value")
            lo_values, hi_values = grid_path.get("low"), grid_path.get("high")
            lo = _number(lo_values[index], v) if isinstance(lo_values, list) and lo_values else v
            hi = _number(hi_values[index], v) if isinstance(hi_values, list) and hi_values else v
            return v, lo, hi
        g = grid
        gv, gl, gh = tuple(_number(g.get(k), 0.0) for k in ("value", "low", "high"))
        if decarbonization:
            dl, dh = _bounds(decarbonization)
            gv *= max(0.0, 1.0 - _number(decarbonization.get("value"), 0.0)) ** year_index
            gl *= max(0.0, 1.0 - dh) ** year_index
            gh *= max(0.0, 1.0 - dl) ** year_index
        return gv, gl, gh
    vals, low_vals, high_vals = [], [], []
    for y in range(count):
        gv, gl, gh = annual_grid(y)
        kwh, miles, kg_per_mile = (_number(x.get("value"), 0) for x in (energy, travel, vehicle))
        vals.append(kwh * gv + miles * kg_per_mile)
        low_vals.append(_bounds(energy)[0] * gl + _bounds(travel)[0] * _bounds(vehicle)[0])
        high_vals.append(_bounds(energy)[1] * gh + _bounds(travel)[1] * _bounds(vehicle)[1])
    central = _number(embodied.get("value"), 0) + sum(vals)
    # Conservative interval propagation from independent declared bands.
    elo, ehi = _bounds(embodied)
    yearly = [_number(embodied.get("value"), 0.0)]
    yearly_low = [elo]
    yearly_high = [ehi]
    for index in range(count):
        yearly.append(yearly[-1] + vals[index])
        yearly_low.append(yearly_low[-1] + low_vals[index])
        yearly_high.append(yearly_high[-1] + high_vals[index])
    low, high = yearly_low[-1], yearly_high[-1]
    used = [embodied, energy, travel, vehicle, *([grid_path] if grid_path else [grid])]
    if not grid_path and decarbonization:
        used.append(decarbonization)
    provs = {item.get("provenance", "modeled") for item in used}
    provenance = "placeholder" if "placeholder" in provs else "assumption" if "assumption" in provs else "modeled"
    ids = sorted({sid for item in used for sid in item.get("source_ids", [])})
    limitations = (
        "Combines prototype materials, operational electricity, household travel and annual grid factors. "
        "The connected materials proxy covers gross A1–A3 structure, enclosure and foundation only; "
        "interiors, MEP, appliances, site works, A4–A5, replacements and end-of-life are not quantified. "
        "No biogenic-storage credit is deducted. Excludes unprovided fuel, fleet-transition and construction-specific data. "
        "The cumulative range conservatively combines input bands and each year's grid-scenario extrema; "
        "it may switch grid pathways between years and is not a coherent named-pathway range or confidence interval."
    )
    extrapolation = "none"
    if grid_path and trajectory_years:
        methods = []
        if base_year < min(trajectory_years):
            methods.append("leading_year_hold")
            limitations = _merge_text(limitations, "Years before the first supplied grid year hold the first modeled rate constant.")
        if base_year + count - 1 > max(trajectory_years):
            methods.append("terminal_year_hold")
            limitations = _merge_text(limitations, "Years after the last supplied grid year hold the last modeled rate constant.")
        extrapolation = ";".join(methods) if methods else "none"
    return {"value": central, "low": min(low, central), "high": max(high, central),
            "unit": "kgCO2e/home over analysis period", "provenance": provenance,
            "evidence_tier": "modeled_scenario", "interval_type": "conservative_input_and_annual_extrema_envelope",
            "geography": "typology and source geography scenario", "source_ids": ids, "as_of": None,
            "partial": True,
            "components_included": ["A1–A3 structure/enclosure/foundation materials proxy", "operational electricity estimate", "household travel with static vehicle factor", "grid electricity emissions"],
            "components_omitted": ["interiors/MEP/appliances/site works", "A4–A5 material transport and construction", "material replacements and end-of-life", "fuel use/emissions", "future vehicle fleet and electrification trajectory", "EV charging electricity where applicable", "construction-specific bill of quantities"],
            "limitations": _merge_text(limitations, "Partial carbon screen: fuel and vehicle fleet transition are not modeled; do not present as a complete whole-life carbon total."),
            "confirmation_needed": "Design-specific quantities and energy model; scenario and source review", "analysis_years": count,
            "analysis_start_year": base_year,
            "grid_path_years": list(trajectory_years) if trajectory_years else None,
            "grid_path_extrapolation": extrapolation,
            "carbon_series": {
                "years": list(range(count + 1)), "value": yearly,
                "low": [min(a, b) for a, b in zip(yearly_low, yearly)],
                "high": [max(a, b) for a, b in zip(yearly_high, yearly)],
                "provenance": provenance,
            }}


def _bounds(envelope: dict) -> tuple[float, float]:
    center = _number(envelope.get("value"), 0.0)
    return _number(envelope.get("low"), center), _number(envelope.get("high"), center)


def _context_envelope(value: Any) -> dict | None:
    if value is None:
        return None
    out = _normalize(value, "historical overflow context")
    out["limitations"] = _merge_text(
        out.get("limitations"),
        "Historical overflow is context only and does not measure parcel-specific contribution or current sewer capacity.",
    )
    out["confirmation_needed"] = "Verify outfall/sewershed linkage and current utility review"
    return out


def _sewer_geography(parcel: dict) -> str:
    if parcel.get("sewershed_id"):
        return f"mapped sewershed {parcel['sewershed_id']}"
    return "unresolved parcel sewer geography"


def _number(value: Any, fallback: float | None = 0.0) -> float | None:
    try:
        if value is None or value == "":
            return fallback
        return float(value)
    except (TypeError, ValueError):
        return fallback


def _is_annual_travel(unit: str) -> bool:
    normalized = unit.lower().replace(" ", "")
    return "/yr" in normalized or "/year" in normalized or normalized.endswith("peryear")


def _merge_text(*parts: Any) -> str:
    return "; ".join(dict.fromkeys(str(p).strip() for p in parts if p and str(p).strip()))
