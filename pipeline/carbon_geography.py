"""Offline parcel-level context for travel VMT and grid-emissions scenarios.

The checked-in model file contains compact, transformed source rows. This
module does no network access at request time and caches the decoded JSON only
for as long as its file path, mtime, and size remain unchanged.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from core.artifact_files import replace_text

MODEL_PATH = Path(__file__).resolve().parents[1] / "data" / "models" / "carbon_geography.json"
_MODEL_CACHE: dict[str, tuple[tuple[int, int], dict[str, Any]]] = {}

LATCH_DOWNLOAD_URL = "https://data.transportation.gov/api/v3/views/va72-z8hz/export.csv?accessType=DOWNLOAD"
CAMBIUM_DOWNLOAD_URL = "https://data.nlr.gov/system/files/289/1744314776-Cambium24_Workbook.xlsx"


def _load_model() -> dict[str, Any]:
    path = Path(MODEL_PATH)
    stat = path.stat()
    signature = (stat.st_mtime_ns, stat.st_size)
    cache_key = str(path.resolve())
    cached = _MODEL_CACHE.get(cache_key)
    if cached and cached[0] == signature:
        return cached[1]
    model = json.loads(path.read_text(encoding="utf-8"))
    _MODEL_CACHE[cache_key] = (signature, model)
    return model


def build_geographic_inputs(parcel: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Build evidence envelopes for annual household VMT and grid factors.

    Direct LATCH matches are exact 11-digit string matches to its 2010 tract
    codes. Since Lotline parcel tracts are from 2024 ACS geography, an exact
    code match is explicitly treated as a 2010-code proxy, never as a verified
    boundary crosswalk. Missing or unusable tract values fall back to a
    household-weighted county LATCH estimate, then state/national estimates.
    """
    model = _load_model()
    parcel = parcel if isinstance(parcel, dict) else {}
    county_fips, county_method = _parcel_county(model, parcel)
    tract = _tract_geoid(parcel)

    result = {
        "vmt_per_household_yr": _vmt_envelope(model, tract, county_fips, county_method, parcel),
    }
    region, grid_geography, grid_fallback = _parcel_grid_region(
        model, parcel, county_fips, county_method
    )
    if region:
        scalar, path, decarb = _grid_envelopes(
            model, region, grid_geography, grid_fallback
        )
        result.update({
            "grid_kgco2e_per_kwh": scalar,
            "grid_kgco2e_by_year": path,
            "grid_decarbonization_per_yr": decarb,
        })
    return result


def _text(value: Any) -> str | None:
    if value is None:
        return None
    string = str(value).strip()
    return string or None


def _tract_geoid(parcel: dict[str, Any]) -> str | None:
    for key in ("tract", "tract_geoid", "census_tract", "tract_fips"):
        value = _text(parcel.get(key))
        if value and value.isdigit() and len(value) == 11:
            return value
    return None


def _digits_fips(value: Any, length: int) -> str | None:
    text = _text(value)
    if text is None:
        return None
    try:
        number = float(text)
        if number.is_integer() and 0 <= number < 10**length:
            return str(int(number)).zfill(length)
    except (ValueError, OverflowError):
        pass
    digits = "".join(character for character in text if character.isdigit())
    if len(digits) == length:
        return digits
    if digits and len(digits) < length:
        return digits.zfill(length)
    return None


def _parcel_county(model: dict[str, Any], parcel: dict[str, Any]) -> tuple[str | None, str | None]:
    tract = _tract_geoid(parcel)
    if tract:
        return tract[:5], "county inferred from first five digits of parcel tract GEOID"

    for key in ("county_fips", "county_geoid", "county_code"):
        county = _digits_fips(parcel.get(key), 5)
        if county:
            return county, f"parcel {key}"

    state_fips = _digits_fips(parcel.get("state_fips"), 2)
    county_part = _digits_fips(parcel.get("county_fips3"), 3)
    if state_fips and county_part:
        return state_fips + county_part, "parcel state/county FIPS fields"

    county_name = _text(parcel.get("county"))
    state_name = _text(parcel.get("state"))
    if county_name:
        pieces = county_name.split(",", 1)
        county_name = pieces[0].strip()
        if not state_name and len(pieces) == 2:
            state_name = pieces[1].strip()
        if county_name.casefold().endswith(" county"):
            county_name = county_name[:-7].strip()
        county_name = county_name.casefold()
        state_fips = _parcel_state_fips(model, parcel)
        matches = []
        for fips, row in model["cambium"]["county_to_region"].items():
            state_matches = not state_name or state_name.casefold() in {
                row["state"].casefold(),
                row.get("state_name", "").casefold(),
                fips[:2],
            }
            if row["county"].casefold() == county_name and state_matches:
                matches.append(fips)
        if len(matches) == 1:
            return matches[0], "parcel county/state name matched to Cambium county crosswalk"
        if county_name:
            return None, "parcel county name unresolved by available Cambium county crosswalk"

    if state_fips or state_name:
        return None, "parcel state only; state aggregate fallback"

    # Lotline's parcel universe is Pittsburgh/Allegheny County. If a record
    # lacks every geography key, keep that project-market fallback visible.
    return "42003", "configured Pittsburgh-market Allegheny County fallback"


def _vmt_envelope(
    model: dict[str, Any],
    tract: str | None,
    county_fips: str | None,
    county_method: str | None,
    parcel: dict[str, Any],
) -> dict[str, Any]:
    latch = model["latch"]
    sources = model["sources"]
    direct = latch["direct_tract_weekday_vmt"].get(tract) if tract else None
    limitations = [
        "LATCH is a 2017 modeled average household weekday travel estimate, not parcel-specific observed travel or a current household measurement.",
        "The annualization ratio transfers a national driver-level NHTS weekday/weekend ratio to tract-level household VMT; the measures and geographies do not match exactly.",
        "The low/high range propagates the published NHTS MOE endpoints for the weekday/weekend ratio only; it does not quantify LATCH model error or tract sampling uncertainty.",
    ]

    if direct:
        weekday = float(direct["avg_weekday_household_vmiles"])
        flags = direct.get("source_flags") or {}
        source_ids = ["bts_latch_2017", "fhwa_nhts_2017_annualization"]
        geography: dict[str, Any] = {
            "type": "tract",
            "geoid": tract,
            "vintage": "2010 LATCH tract code; exact-code proxy only",
            "parcel_tract_vintage": "2024 ACS tract geography",
            "join_method": "exact 11-digit GEOID string equality; no Census tract relationship-file crosswalk",
        }
        fallback = None
        limitations.insert(
            0,
            "Exact tract-code equality does not verify that a 2010 LATCH tract and 2024 ACS tract share boundaries; no Census relationship crosswalk was applied.",
        )
        if flags.get("flag_acs_lt_moe") == "1":
            limitations.append(
                "Source flag_acs_lt_moe=1: an ACS explanatory-variable estimate had a margin of error larger than its estimate; this flag is retained and is not a travel confidence interval."
            )
    else:
        county_data = latch["county_weekday_vmt"].get(county_fips) if county_fips else None
        fallback = "county"
        if county_data:
            weekday = float(county_data["avg_weekday_household_vmiles"])
            geography = {
                "type": "county",
                "geoid": county_fips,
                "name": _county_name(model, county_fips),
                "vintage": "2010 LATCH tract aggregates",
                "join_method": county_method or "county FIPS",
            }
            limitations.insert(
                0,
                "No usable direct LATCH record was available for this parcel tract; using the household-count-weighted mean of county LATCH tract estimates.",
            )
            limitations.append(
                f"County mean includes {county_data['tracts_with_valid_vmt']} usable LATCH tract records out of {county_data['tract_records_total']} county records; underlying LATCH suppression/model uncertainty is not quantified here."
            )
        else:
            state_fips = county_fips[:2] if county_fips else _parcel_state_fips(model, parcel)
            state_data = latch.get("state_weekday_vmt", {}).get(state_fips) if state_fips else None
            if state_data:
                weekday = float(state_data["avg_weekday_household_vmiles"])
                geography = {"type": "state", "fips": state_fips, "vintage": "2010 LATCH tract aggregates"}
                fallback = "state"
                limitations.insert(0, "County LATCH fallback was unavailable; using the household-count-weighted mean of state LATCH tract estimates.")
            else:
                nationwide = latch["national_weekday_vmt"]
                weekday = float(nationwide["avg_weekday_household_vmiles"])
                geography = {"type": "United States", "vintage": "2010 LATCH tract aggregates"}
                fallback = "national"
                limitations.insert(0, "No usable parcel tract, county, or state LATCH estimate was available; using the national household-count-weighted LATCH tract mean.")

    annual = latch["annualization"]
    factors = annual["equivalent_days_per_year"]
    value = weekday * float(factors["central"])
    low = weekday * float(factors["low"])
    high = weekday * float(factors["high"])
    if not direct and county_fips is None and fallback in ("national", "state"):
        # Do not silently assign a distant/publisher geography as if it matched.
        geography["fallback_level"] = fallback
    if (
        not direct
        and county_fips == "42003"
        and not tract
        and county_method == "configured Pittsburgh-market Allegheny County fallback"
    ):
        limitations.insert(
            0,
            "This parcel has no tract or county identifier; the configured Pittsburgh-market Allegheny County fallback was applied.",
        )

    source_ids = ["bts_latch_2017", "fhwa_nhts_2017_annualization"]
    latch_hash = sources["bts_latch_2017"]["sha256"]
    return {
        "value": round(value, 2),
        "low": round(low, 2),
        "high": round(high, 2),
        "unit": "miles/household/yr",
        "provenance": "modeled",
        "evidence_tier": "geographic_estimate",
        "interval_type": "NHTS_MOE_endpoint_annualization_scenario",
        "geography": geography,
        "source_ids": source_ids,
        "source_snapshot_ids": [latch_hash],
        "as_of": "2017 LATCH and 2017 NHTS; retrieved 2026-09-27",
        "model_id": f"latch_2017_annualized_{fallback or 'tract_proxy'}_v1",
        "model_version": model["model_version"],
        "weekday_value_miles_per_household_day": round(weekday, 6),
        "annualization": {
            "weekdays_per_year": annual["weekday_days_per_year"],
            "weekend_days_per_year": annual["weekend_days_per_year"],
            "weekend_to_weekday_ratio": annual["weekend_to_weekday_ratio"],
            "ratio_scenario_bounds": annual["ratio_scenario_bounds"],
            "equivalent_days_per_year": factors,
            "method": "weekday daily household estimate * (261 + 104 * national NHTS weekend/weekday VMT ratio)",
        },
        "source_flags": direct.get("source_flags") if direct else None,
        "fallback_level": fallback,
        "limitations": limitations,
        "confirmation_needed": "Replace with a household travel survey or project-specific transportation analysis when available.",
    }


def _county_name(model: dict[str, Any], fips: str | None) -> str | None:
    row = model["cambium"]["county_to_region"].get(fips or "")
    if row:
        return f"{row['county']} County, {row['state']}"
    return None


def _parcel_grid_region(
    model: dict[str, Any], parcel: dict[str, Any], county_fips: str | None, county_method: str | None
) -> tuple[str, dict[str, Any], str | None]:
    cambium = model["cambium"]
    mapping = cambium["county_to_region"].get(county_fips or "")
    if mapping:
        return mapping["gea_region"], {
            "type": "Cambium GEA region",
            "id": mapping["gea_region"],
            "county_fips": county_fips,
            "county": mapping["county"],
            "state": mapping["state"],
            "state_name": mapping.get("state_name"),
            "reeds_balancing_area": mapping["reeds_balancing_area"],
            "mapping_source": "Cambium 2024 County Mapping sheet; county to ReEDS balancing area to GEA region",
            "parcel_join_method": county_method or "parcel county FIPS",
        }, None

    state_fips = county_fips[:2] if county_fips else _parcel_state_fips(model, parcel)
    state_region = cambium.get("state_primary_regions", {}).get(state_fips or "")
    if state_region:
        region = state_region["gea_region"]
        return region, {
            "type": "Cambium GEA region state proxy",
            "id": region,
            "state_fips": state_fips,
            "mapped_counties": state_region["county_count"],
            "county_region_counts": state_region["region_counts"],
            "parcel_join_method": "most common Cambium county-region assignment within state; county mapping missing",
        }, "state_proxy"

    region = cambium["fallback_region"]
    return region, {
        "type": "configured Pittsburgh-market Cambium fallback",
        "id": region,
        "parcel_join_method": "parcel county/state mapping unavailable; project market default",
    }, "project_region_fallback"


def _interpolate(values: list[float], source_years: list[int], target_year: int) -> float:
    if target_year <= source_years[0]:
        return float(values[0])
    if target_year >= source_years[-1]:
        return float(values[-1])
    for left in range(len(source_years) - 1):
        y0, y1 = source_years[left], source_years[left + 1]
        if y0 <= target_year <= y1:
            ratio = (target_year - y0) / (y1 - y0)
            return float(values[left]) + ratio * (float(values[left + 1]) - float(values[left]))
    raise ValueError(f"year {target_year} falls outside Cambium source years")


def _grid_envelopes(
    model: dict[str, Any], region: str, geography: dict[str, Any], fallback: str | None
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    cambium = model["cambium"]
    sources = model["sources"]
    scenarios: dict[str, list[float]] = cambium["regions"][region]
    source_years = [int(year) for year in cambium["source_years"]]
    annual_years = list(range(source_years[0], source_years[-1] + 1))
    mid_name = "Mid-case"
    annualized = {
        name: [_interpolate(values, source_years, year) for year in annual_years]
        for name, values in scenarios.items()
    }
    central_series = annualized[mid_name]
    low_series = [min(values[index] for values in annualized.values()) for index in range(len(annual_years))]
    high_series = [max(values[index] for values in annualized.values()) for index in range(len(annual_years))]
    cambium_hash = sources["nrel_cambium_2024"]["sha256"]
    source_ids = ["nrel_cambium_2024"]
    limitations = [
        "Cambium scenarios are modeled futures, not forecasts; the eight-scenario envelope is scenario spread, not a confidence interval.",
        "Source points are every five years and each pathway is linearly interpolated for intervening years.",
        "AER load CO2e includes direct and precombustion CO2, CH4, and N2O on an end-use-demand basis with average distribution losses; do not apply a second loss adjustment.",
        "County-to-GEA assignment follows the Cambium 2024 county/ReEDS balancing area crosswalk and does not verify the parcel's electric utility or meter service territory.",
        "Cambium source data stop at 2050. Carbon calculations extending later hold the 2050 scenario endpoint; alternative 2050 scenario endpoints are exposed as the terminal sensitivity range, not as a post-2050 forecast.",
    ]
    if fallback == "state_proxy":
        limitations.insert(0, "County mapping was unavailable; the most common Cambium region among mapped counties in the parcel state was used as an explicit state proxy.")
    elif fallback == "project_region_fallback":
        limitations.insert(0, "County and state could not be mapped; PJM_East is used as the configured Pittsburgh-market fallback, not as an inferred parcel-specific grid region.")

    scalar = {
        "value": round(central_series[0], 9),
        "low": round(low_series[0], 9),
        "high": round(high_series[0], 9),
        "unit": "kgCO2e/kWh",
        "provenance": "modeled",
        "evidence_tier": "regional_scenario",
        "interval_type": "Cambium_8_scenario_spread",
        "geography": geography,
        "source_ids": source_ids,
        "source_snapshot_ids": [cambium_hash],
        "as_of": "Cambium 2024 scenarios; 2025 first projection year",
        "model_id": f"cambium_2024_{region}_aer_load_co2e_midcase",
        "model_version": model["model_version"],
        "reference_year": annual_years[0],
        "rate_basis": "AER load (not AER generation), per MWh of end-use demand; average distribution losses are included, so do not apply a second line-loss gross-up.",
        "distribution_loss_adjustment_included": True,
        "limitations": limitations,
        "historical_reference": {
            "value": 0.41551510490798,
            "unit": "kgCO2e/kWh",
            "source_id": "epa_egrid_2023_reference",
            "geography": "RFC West (RFCW) eGRID subregion",
            "as_of": "2023 generation and emissions; Revision 2 released 2025-06-12",
            "limitations": "Historical eGRID reference only; it is not the same geography or end-use-rate boundary as Cambium PJM_East and is not a projection.",
        },
    }
    terminal_scenarios = {name: round(values[-1], 9) for name, values in annualized.items()}
    path = {
        "value": [round(value, 9) for value in central_series],
        "low": [round(value, 9) for value in low_series],
        "high": [round(value, 9) for value in high_series],
        "years": annual_years,
        "unit": "kgCO2e/kWh",
        "provenance": "modeled",
        "evidence_tier": "regional_scenario",
        "interval_type": "Cambium_8_scenario_spread_by_year",
        "geography": geography,
        "source_ids": source_ids,
        "source_snapshot_ids": [cambium_hash],
        "as_of": "Cambium 2024 scenarios; 2025–2050",
        "model_id": f"cambium_2024_{region}_annual_aer_load_co2e",
        "model_version": model["model_version"],
        "rate_basis": "AER load (not AER generation), per MWh of end-use demand; average distribution losses are included, so do not apply a second line-loss gross-up.",
        "distribution_loss_adjustment_included": True,
        "source_years": source_years,
        "scenario_names": list(annualized),
        "interpolation": "linear within each Cambium five-year interval",
        "extrapolation": {
            "method": "terminal_year_hold",
            "terminal_year": annual_years[-1],
            "value": round(central_series[-1], 9),
            "low": round(low_series[-1], 9),
            "high": round(high_series[-1], 9),
            "alternative_scenario_terminal_values": terminal_scenarios,
            "limitation": "Holding a 2050 modeled endpoint constant after 2050 is a transparent sensitivity convention, not a forecast. The listed scenario terminal values show alternative model pathways through 2050 only.",
        },
        "limitations": limitations,
    }
    cagr_by_scenario = {
        name: 1.0 - (values[-1] / values[0]) ** (1.0 / (annual_years[-1] - annual_years[0]))
        for name, values in annualized.items()
    }
    decarb = {
        "value": round(cagr_by_scenario[mid_name], 9),
        "low": round(min(cagr_by_scenario.values()), 9),
        "high": round(max(cagr_by_scenario.values()), 9),
        "unit": "share/year",
        "provenance": "modeled",
        "evidence_tier": "derived_scenario_summary",
        "interval_type": "Cambium_8_scenario_CAGR_range",
        "geography": geography,
        "source_ids": source_ids,
        "source_snapshot_ids": [cambium_hash],
        "as_of": "Cambium 2024, 2025–2050 endpoints",
        "model_id": f"cambium_2024_{region}_endpoint_cagr_summary",
        "method": "1 - (2050 / 2025 rate) ** (1 / 25); central is Mid-case; low/high span scenario-specific endpoint CAGR",
        "limitations": [
            "Descriptive compound annual decline derived from 2025 and 2050 modeled endpoints; it hides non-monotonic year-to-year paths.",
            "The annual grid trajectory is the authoritative input; this summary should not replace the supplied path.",
            "Scenario spread is not a statistical confidence interval.",
        ],
    }
    return scalar, path, decarb


def _parcel_state_fips(model: dict[str, Any], parcel: dict[str, Any]) -> str | None:
    state_fips = _digits_fips(parcel.get("state_fips"), 2)
    if state_fips:
        return state_fips
    state = _text(parcel.get("state"))
    if state:
        lookup = model.get("state_abbreviation_to_fips", {})
        state_fips = lookup.get(state.upper())
        if state_fips:
            return state_fips
        return model.get("state_name_to_fips", {}).get(state.casefold())
    return None


def refresh_model_data(
    latch_csv_path: str | Path | None = None,
    cambium_xlsx_path: str | Path | None = None,
    parcels_json_path: str | Path | None = None,
    output_path: str | Path | None = None,
) -> dict[str, Any]:
    """Rebuild the checked-in snapshot from official BTS/NLR source files.

    Pass both local ``latch_csv_path`` and ``cambium_xlsx_path`` for an offline
    refresh. If either is omitted, the official public download is fetched into
    a temporary directory using Python's standard-library URL client. Network
    access is therefore optional and never occurs in ``build_geographic_inputs``.
    """
    import tempfile
    from datetime import UTC, datetime

    from_source_parcels = Path(parcels_json_path) if parcels_json_path else Path(__file__).resolve().parents[1] / "data" / "processed" / "parcels.json"
    out_path = Path(output_path) if output_path else MODEL_PATH
    with tempfile.TemporaryDirectory(prefix="lotline-carbon-geography-") as temp_name:
        temp_dir = Path(temp_name)
        local_latch = Path(latch_csv_path) if latch_csv_path else temp_dir / "latch2017.csv"
        local_cambium = Path(cambium_xlsx_path) if cambium_xlsx_path else temp_dir / "cambium2024.xlsx"
        if latch_csv_path is None:
            _download_source(LATCH_DOWNLOAD_URL, local_latch)
        if cambium_xlsx_path is None:
            _download_source(CAMBIUM_DOWNLOAD_URL, local_cambium)
        artifact = _build_model_snapshot(local_latch, local_cambium, from_source_parcels, datetime.now(UTC).date().isoformat())
        out_path.parent.mkdir(parents=True, exist_ok=True)
        replace_text(out_path, json.dumps(artifact, sort_keys=True, separators=(",", ":")) + "\n")
    # Force the serving process to notice the refreshed stat signature.
    cache_key = str(out_path.resolve())
    _MODEL_CACHE.pop(cache_key, None)
    return {
        "output_path": str(out_path),
        "model_version": artifact["model_version"],
        "latch_direct_tracts": len(artifact["latch"]["direct_tract_weekday_vmt"]),
        "latch_counties": len(artifact["latch"]["county_weekday_vmt"]),
        "cambium_regions": len(artifact["cambium"]["regions"]),
        "mapped_counties": len(artifact["cambium"]["county_to_region"]),
        "coverage_audit": artifact["parcel_geography_vintage"]["coverage_audit"],
    }


def _download_source(url: str, destination: Path) -> None:
    from shutil import copyfileobj
    from urllib.request import Request, urlopen

    request = Request(url, headers={"User-Agent": "Lotline carbon geography source refresh/1.0"})
    with urlopen(request, timeout=180) as response, destination.open("wb") as target:
        copyfileobj(response, target)


def _sha256(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _parcel_records(path: Path) -> list[dict[str, Any]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    rows = raw.get("parcels", raw) if isinstance(raw, dict) else raw
    if isinstance(rows, dict):
        return [row for row in rows.values() if isinstance(row, dict)]
    return [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []


def _fips_part(value: Any, width: int) -> str | None:
    text = _text(value)
    if text is None:
        return None
    try:
        return str(int(float(text))).zfill(width)
    except (TypeError, ValueError, OverflowError):
        digits = "".join(ch for ch in text if ch.isdigit())
        return digits.zfill(width) if 0 < len(digits) <= width else None


def _build_model_snapshot(latch_path: Path, cambium_path: Path, parcels_path: Path, model_date: str) -> dict[str, Any]:
    import csv
    from collections import Counter, defaultdict

    parcel_rows = _parcel_records(parcels_path)
    parcel_tract_counts: Counter[str] = Counter(
        tract for row in parcel_rows if (tract := _tract_geoid(row))
    )
    direct_tracts: dict[str, dict[str, Any]] = {}
    county_total: Counter[str] = Counter()
    county_numerator: defaultdict[str, float] = defaultdict(float)
    county_households: defaultdict[str, float] = defaultdict(float)
    county_valid: Counter[str] = Counter()
    state_numerator: defaultdict[str, float] = defaultdict(float)
    state_households: defaultdict[str, float] = defaultdict(float)
    state_valid: Counter[str] = Counter()
    national_numerator = 0.0
    national_households = 0.0
    national_valid = 0
    with latch_path.open(newline="", encoding="utf-8-sig") as source:
        for row in csv.DictReader(source):
            tract = _text(row.get("geocode"))
            if not tract or not tract.isdigit() or len(tract) != 11:
                continue
            county = tract[:5]
            county_total[county] += 1
            try:
                daily_vmt = float((row.get("est_vmiles") or "").replace(",", "").strip())
                households = float((row.get("hh_cnt") or "").replace(",", "").strip())
            except (TypeError, ValueError):
                continue
            if not math.isfinite(daily_vmt) or not math.isfinite(households) or households <= 0:
                continue
            county_numerator[county] += daily_vmt * households
            county_households[county] += households
            county_valid[county] += 1
            state = tract[:2]
            state_numerator[state] += daily_vmt * households
            state_households[state] += households
            state_valid[state] += 1
            national_numerator += daily_vmt * households
            national_households += households
            national_valid += 1
            if tract in parcel_tract_counts:
                direct_tracts[tract] = {
                    "avg_weekday_household_vmiles": round(daily_vmt, 6),
                    "household_count_weight": round(households, 3),
                    "source_flags": {
                        key: (_text(row.get(key)))
                        for key in ("flag_acs_lt_moe", "flag_manhattan_trt", "flag_gpqtr", "flag_incomplete_acs")
                    },
                }

    counties = {
        county: {
            "avg_weekday_household_vmiles": round(county_numerator[county] / county_households[county], 6),
            "households_weighted": round(county_households[county], 3),
            "tracts_with_valid_vmt": county_valid[county],
            "tract_records_total": county_total[county],
        }
        for county in county_numerator
    }
    states = {
        state: {
            "avg_weekday_household_vmiles": round(state_numerator[state] / state_households[state], 6),
            "households_weighted": round(state_households[state], 3),
            "tracts_with_valid_vmt": state_valid[state],
        }
        for state in state_numerator
    }
    nhts = _nhts_annualization()
    cambium, state_abbreviations = _parse_cambium_workbook(cambium_path)

    direct_parcel_count = sum(parcel_tract_counts[tract] for tract in direct_tracts)
    parcel_count = len(parcel_rows)
    no_tract_count = sum(not _tract_geoid(row) for row in parcel_rows)
    coverage = {
        "current_parcels_total": parcel_count,
        "current_parcels_with_tract": sum(parcel_tract_counts.values()),
        "unique_current_parcel_tracts": len(parcel_tract_counts),
        "unique_current_tracts_with_direct_latch_values": len(direct_tracts),
        "parcels_with_same_code_tract_proxy": direct_parcel_count,
        "parcels_with_tract_using_county_fallback": sum(
            count for tract, count in parcel_tract_counts.items() if tract not in direct_tracts
        ),
        "parcels_without_tract_using_project_county_fallback": no_tract_count,
        "direct_latch_tracts_flagged_acs_lt_moe": sum(
            record["source_flags"].get("flag_acs_lt_moe") == "1" for record in direct_tracts.values()
        ),
    }
    return _snapshot_document(
        latch_path,
        cambium_path,
        direct_tracts,
        counties,
        states,
        national_numerator,
        national_households,
        national_valid,
        nhts,
        cambium,
        state_abbreviations,
        coverage,
        model_date,
    )


def _nhts_annualization() -> dict[str, Any]:
    # FHWA 2017 NHTS Summary of Travel Trends, Table 30: original national
    # average daily VMT per driver, weekday 26.9 (MOE 1.5), weekend 23.2 (0.8).
    weekday, weekday_moe = 26.9, 1.5
    weekend, weekend_moe = 23.2, 0.8
    ratio = weekend / weekday
    ratio_low = (weekend - weekend_moe) / (weekday + weekday_moe)
    ratio_high = (weekend + weekend_moe) / (weekday - weekday_moe)
    factors = {
        "low": 261 + 104 * ratio_low,
        "central": 261 + 104 * ratio,
        "high": 261 + 104 * ratio_high,
    }
    return {
        "ratio": ratio,
        "ratio_low": ratio_low,
        "ratio_high": ratio_high,
        "weekday_days": 261,
        "weekend_days": 104,
        "factors": factors,
        "weekday_vmt": weekday,
        "weekday_moe": weekday_moe,
        "weekend_vmt": weekend,
        "weekend_moe": weekend_moe,
    }


def _xlsx_sheet_rows(archive: Any, path: str) -> list[tuple[int, dict[str, Any]]]:
    from xml.etree import ElementTree as ET

    ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    shared_values: list[str] = []
    if "xl/sharedStrings.xml" in archive.namelist():
        shared_root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
        shared_values = [
            "".join(text.text or "" for text in item.findall(".//m:t", ns))
            for item in shared_root.findall("m:si", ns)
        ]
    root = ET.fromstring(archive.read(path))
    result = []
    for row in root.findall(".//m:sheetData/m:row", ns):
        values: dict[str, Any] = {}
        for cell in row.findall("m:c", ns):
            value = cell.find("m:v", ns)
            if value is None:
                inline = cell.find("m:is", ns)
                if inline is None:
                    continue
                cell_value: Any = "".join(text.text or "" for text in inline.findall(".//m:t", ns))
            elif cell.attrib.get("t") == "s":
                cell_value = shared_values[int(value.text)]
            else:
                cell_value = value.text
            values[cell.attrib["r"]] = cell_value
        result.append((int(row.attrib["r"]), values))
    return result


def _excel_column(ref: str) -> int:
    import re

    letters = re.match(r"[A-Z]+", ref)
    if letters is None:
        return 0
    value = 0
    for character in letters.group(0):
        value = value * 26 + ord(character) - ord("A") + 1
    return value


def _column_letter(value: int) -> str:
    text = ""
    while value:
        value, remainder = divmod(value - 1, 26)
        text = chr(ord("A") + remainder) + text
    return text


def _workbook_sheets(archive: Any) -> dict[str, str]:
    from xml.etree import ElementTree as ET

    main_ns = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    rel_ns = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    package_ns = "http://schemas.openxmlformats.org/package/2006/relationships"
    workbook = ET.fromstring(archive.read("xl/workbook.xml"))
    relationships = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
    targets = {
        row.attrib["Id"]: row.attrib["Target"]
        for row in relationships.findall(f"{{{package_ns}}}Relationship")
        if row.attrib.get("Type", "").endswith("/worksheet")
    }
    result = {}
    for sheet in workbook.findall(f"{{{main_ns}}}sheets/{{{main_ns}}}sheet"):
        relationship_id = sheet.attrib[f"{{{rel_ns}}}id"]
        target = targets[relationship_id]
        result[sheet.attrib["name"]] = target if target.startswith("xl/") else f"xl/{target}"
    return result


def _parse_cambium_workbook(path: Path) -> tuple[dict[str, Any], dict[str, str]]:
    import re
    from zipfile import ZipFile

    with ZipFile(path) as archive:
        sheets = _workbook_sheets(archive)
        annual_rows = _xlsx_sheet_rows(archive, sheets["Data - Annual"])
        mapping_rows = _xlsx_sheet_rows(archive, sheets["County Mapping"])
        gwp_rows = _xlsx_sheet_rows(archive, sheets["GWP"])
    annual_by_number = {number: cells for number, cells in annual_rows}

    def value(row_number: int, column: int) -> Any:
        return annual_by_number.get(row_number, {}).get(f"{_column_letter(column)}{row_number}")

    # Use the workbook's component labels and source years rather than baking
    # component positions or five-year dates into the parser.
    components: dict[tuple[str, str], int] = {}
    for cell_ref, label in annual_by_number.get(3, {}).items():
        if not isinstance(label, str):
            continue
        match = re.match(r"(CO2|CH4|N2O) from (Direct Combustion|Precombustion)", label)
        if match:
            gas = match.group(1)
            process = "direct" if match.group(2) == "Direct Combustion" else "precombustion"
            components[(gas, process)] = _excel_column(cell_ref)
    expected_components = {
        (gas, process)
        for gas in ("CO2", "CH4", "N2O")
        for process in ("direct", "precombustion")
    }
    if set(components) != expected_components:
        raise ValueError(f"Cambium annual sheet lacks required emissions component labels: {components}")

    first_component_col = components[("CO2", "direct")]
    next_component_col = min(
        (column for column in components.values() if column > first_component_col),
        default=first_component_col + 48,
    )
    scenario_headers = sorted(
        (
            _excel_column(cell_ref), label
        )
        for cell_ref, label in annual_by_number.get(4, {}).items()
        if first_component_col <= _excel_column(cell_ref) < next_component_col
        and isinstance(label, str)
        and label.strip()
    )
    if not scenario_headers:
        raise ValueError("Cambium annual sheet has no scenario headers")
    years: list[int] = []
    for offset in range(6):
        raw_year = value(5, scenario_headers[0][0] + offset)
        if raw_year is None:
            break
        years.append(int(float(raw_year)))
    if len(years) < 2:
        raise ValueError("Cambium annual sheet has fewer than two projection years")

    gwp_ch4 = 29.8
    gwp_n2o = 273.0
    for row_number, cells in gwp_rows:
        if cells.get(f"B{row_number}") == "100-year (AR6)":
            gwp_ch4 = float(cells[f"D{row_number}"])
            gwp_n2o = float(cells[f"E{row_number}"])
            break

    region_rows: dict[str, tuple[int, dict[str, Any]]] = {}
    for row_number, cells in annual_rows:
        region = _text(cells.get(f"B{row_number}"))
        if row_number >= 6 and region and region != "Region":
            region_rows[region] = (row_number, cells)
    trajectories: dict[str, dict[str, list[float]]] = {}
    scenario_names = [name for _, name in scenario_headers]
    if len(set(scenario_names)) != len(scenario_names):
        raise ValueError("Cambium workbook contains duplicate scenario names")
    for region, (row_number, cells) in region_rows.items():
        trajectories[region] = {}
        for scenario_col, scenario_name in scenario_headers:
            scenario_offset = scenario_col - scenario_headers[0][0]
            values = []
            for year_index, _year in enumerate(years):
                emissions = {}
                for component, first_column in components.items():
                    column = first_column + scenario_offset + year_index
                    raw = cells.get(f"{_column_letter(column)}{row_number}")
                    if raw is None:
                        raise ValueError(f"Missing Cambium value {region}/{scenario_name}/{_year}/{component}")
                    emissions[component] = float(raw)

                co2 = emissions[("CO2", "direct")] + emissions[("CO2", "precombustion")]
                ch4 = emissions[("CH4", "direct")] + emissions[("CH4", "precombustion")]
                n2o = emissions[("N2O", "direct")] + emissions[("N2O", "precombustion")]
                kg_per_mwh = co2 + ch4 * gwp_ch4 / 1000 + n2o * gwp_n2o / 1000
                values.append(round(kg_per_mwh / 1000, 9))
            trajectories[region][scenario_name] = values

    county_to_region: dict[str, dict[str, str]] = {}
    state_abbreviations: dict[str, str] = {}
    state_names: dict[str, str] = {}
    for row_number, cells in mapping_rows:
        if row_number < 2:
            continue
        state_fp = _fips_part(cells.get(f"A{row_number}"), 2)
        county_fp = _fips_part(cells.get(f"B{row_number}"), 3)
        state = _text(cells.get(f"D{row_number}"))
        state_name = _text(cells.get(f"E{row_number}"))
        region = _text(cells.get(f"G{row_number}"))
        county = _text(cells.get(f"C{row_number}"))
        if not state_fp or not county_fp or not state or not region:
            continue
        fips = state_fp + county_fp
        county_to_region[fips] = {
            "county": county or "",
            "state": state,
            "state_name": state_name or "",
            "reeds_balancing_area": _text(cells.get(f"F{row_number}")) or "",
            "gea_region": region,
        }
        state_abbreviations[state] = state_fp
        if state_name:
            state_names[state_name.casefold()] = state_fp
    return {
        "source_years": years,
        "scenarios": scenario_names,
        "regions": trajectories,
        "county_to_region": county_to_region,
        "state_abbreviation_to_fips": state_abbreviations,
        "state_name_to_fips": state_names,
        "gwp_ch4": gwp_ch4,
        "gwp_n2o": gwp_n2o,
    }, state_abbreviations


def _snapshot_document(
    latch_path: Path,
    cambium_path: Path,
    direct_tracts: dict[str, Any],
    counties: dict[str, Any],
    states: dict[str, Any],
    national_numerator: float,
    national_households: float,
    national_valid: int,
    annualization: dict[str, Any],
    cambium: dict[str, Any],
    state_abbreviations: dict[str, str],
    coverage: dict[str, Any],
    model_date: str,
) -> dict[str, Any]:
    scenario_names = cambium["scenarios"]
    source_years = cambium["source_years"]
    county_map = cambium["county_to_region"]
    region_counts: dict[str, dict[str, int]] = {}
    for fips, item in county_map.items():
        state = fips[:2]
        counts = region_counts.setdefault(state, {})
        region = item["gea_region"]
        counts[region] = counts.get(region, 0) + 1
    state_primary = {
        state: {
            "gea_region": max(counts, key=counts.get),
            "county_count": sum(counts.values()),
            "region_counts": dict(sorted(counts.items())),
        }
        for state, counts in region_counts.items()
    }
    nhts_ratio = annualization["ratio"]
    factors = {key: round(value, 6) for key, value in annualization["factors"].items()}
    latch_hash, cambium_hash = _sha256(latch_path), _sha256(cambium_path)
    return {
        "schema_version": 1,
        "model_id": "lotline_carbon_geography_v1",
        "model_version": model_date,
        "sources": {
            "bts_latch_2017": {
                "source_id": "bts_latch_2017",
                "publisher": "Bureau of Transportation Statistics, U.S. Department of Transportation",
                "title": "2017 Local Area Transportation Characteristics by Household (LATCH) tract CSV",
                "url": "https://www.bts.gov/latch/latch-data",
                "catalog_url": "https://catalog.data.gov/dataset/local-area-transportation-characteristics-by-household-2017",
                "download_url": LATCH_DOWNLOAD_URL,
                "vintage": "2017 modeled estimates using 2017 NHTS travel and 2012–2016 ACS covariates",
                "geography": "2010 Census tract GEOIDs; exact-code string joins are 2010-code proxies, not Census relationship-file crosswalks",
                "measure": "Modeled average weekday household vehicle miles traveled per day",
                "sha256": latch_hash,
                "retrieved_at": model_date,
                "limitations": [
                    "LATCH is a model transferred from NHTS/ACS characteristics, not observed travel at a parcel or current household.",
                    "Current parcel tract codes use 2024 ACS geography; an 11-digit value match does not verify matching tract boundaries.",
                    "LATCH values are weekday-only and are not annual household mileage without a separate annualization assumption.",
                    "County/state/national fallback means omit source tract records without valid VMT or a positive household weight.",
                    "LATCH flag_acs_lt_moe is preserved; it flags ACS predictor uncertainty, not a VMT confidence interval.",
                ],
            },
            "fhwa_nhts_2017_annualization": {
                "source_id": "fhwa_nhts_2017_annualization",
                "publisher": "Federal Highway Administration, U.S. Department of Transportation",
                "title": "2017 National Household Travel Survey: Summary of Travel Trends, Table 30",
                "url": "https://www.fhwa.dot.gov/policyinformation/documents/2017_nhts_summary_travel_trends.pdf",
                "table": "Table 30, Weekday vs. Weekend, PDF pages 94–95",
                "vintage": "2017 NHTS original national per-driver VMT statistics",
                "geography": "United States; driver-level ratio transferred to tract-level LATCH household estimate",
                "weekday_vmt_per_driver": annualization["weekday_vmt"],
                "weekday_moe": annualization["weekday_moe"],
                "weekend_vmt_per_driver": annualization["weekend_vmt"],
                "weekend_moe": annualization["weekend_moe"],
                "weekend_to_weekday_ratio": round(nhts_ratio, 9),
                "ratio_scenario_bounds": {"low": round(annualization["ratio_low"], 9), "high": round(annualization["ratio_high"], 9)},
                "weekdays_per_year": annualization["weekday_days"],
                "weekend_days_per_year": annualization["weekend_days"],
                "annualization_equivalent_days": factors,
                "limitations": [
                    "National driver-level weekday/weekend ratio is transferred to household-level LATCH weekday VMT; denominator and geography differ.",
                    "Bounds conservatively propagate Table 30 MOE endpoints and are not a formal ratio confidence interval.",
                    "261 weekdays plus 104 weekend days represents a non-leap-year calendar.",
                ],
            },
            "nrel_cambium_2024": {
                "source_id": "nrel_cambium_2024",
                "publisher": "National Renewable Energy Laboratory",
                "title": "Cambium 2024 Annual Data workbook",
                "url": "https://data.nlr.gov/submissions/289",
                "download_url": CAMBIUM_DOWNLOAD_URL,
                "project_url": "https://scenarioviewer.nlr.gov/?layout=Default&mode=download&project=5c7bef16-7e38-4094-92ce-8b03dfa93380",
                "methodology_url": "https://docs.nlr.gov/docs/fy25osti/93005.pdf",
                "workbook_sheets": ["Data - Annual", "County Mapping", "GWP"],
                "vintage": "2024 scenario release, 2025–2050 source points",
                "geography": "Cambium GEA regions; county mapping through ReEDS balancing area",
                "measure": "AER load CO2e, direct plus precombustion CO2/CH4/N2O per MWh end-use demand; AR6 100-year GWP; end-use basis includes average distribution losses",
                "sha256": cambium_hash,
                "retrieved_at": model_date,
                "source_years": source_years,
                "scenarios": scenario_names,
                "limitations": [
                    "Cambium is a set of modeled futures, not a forecast; scenario spread is not a confidence interval.",
                    "Source points are five years apart and intervening annual rates are linearly interpolated.",
                    "End-use-demand basis includes average distribution losses; do not add another line-loss adjustment.",
                    "County crosswalk does not verify a parcel's electric utility or meter service territory.",
                    "Source horizon ends in 2050; use a disclosed terminal hold or explicit alternative sensitivity after that year.",
                ],
            },
            "epa_egrid_2023_reference": {
                "publisher": "U.S. Environmental Protection Agency",
                "title": "eGRID2023, Revision 2 summary data",
                "url": "https://www.epa.gov/egrid/summary-data",
                "source_id": "epa_egrid_2023_reference",
                "vintage": "2023 generation/emissions; Revision 2 released 2025-06-12",
                "geography": "RFC West (RFCW) eGRID subregion",
                "exact_rate_lb_co2e_per_mwh": 916.054,
                "converted_rate_kgco2e_per_kwh": 0.41551510490798,
                "measure": "Total output emission rate, 916.054 lb CO2e/MWh = 0.415515 kgCO2e/kWh (display 0.416); historical output rate, not a forecast.",
                "limitations": ["RFCW is not Cambium PJM_East and the historical output rate is not Cambium's end-use AER-load boundary."],
            },
        },
        "parcel_geography_vintage": {
            "current_lotline_source": "2020–2024 ACS five-year estimates on 2024 ACS tract geography",
            "current_parcel_dataset": "data/processed/parcels.json at refresh time",
            "coverage_audit": coverage,
            "county_inferred_from_tract_prefix": "For an 11-digit tract GEOID, county is the first five digits.",
            "no_tract_fallback": "An explicit state-only geography uses state aggregates; if all geography keys are absent, use the configured Pittsburgh-market Allegheny County FIPS 42003 fallback.",
        },
        "state_abbreviation_to_fips": state_abbreviations,
        "state_name_to_fips": cambium["state_name_to_fips"],
        "latch": {
            "direct_tract_weekday_vmt": direct_tracts,
            "county_weekday_vmt": counties,
            "state_weekday_vmt": states,
            "national_weekday_vmt": {
                "avg_weekday_household_vmiles": round(national_numerator / national_households, 6),
                "households_weighted": round(national_households, 3),
                "tracts_with_valid_vmt": national_valid,
            },
            "annualization": {
                "weekday_days_per_year": annualization["weekday_days"],
                "weekend_days_per_year": annualization["weekend_days"],
                "weekend_to_weekday_ratio": round(nhts_ratio, 9),
                "ratio_scenario_bounds": {"low": round(annualization["ratio_low"], 9), "high": round(annualization["ratio_high"], 9)},
                "equivalent_days_per_year": factors,
                "weekend_ratio_source_id": "fhwa_nhts_2017_annualization",
            },
        },
        "cambium": {
            "county_to_region": county_map,
            "state_primary_regions": state_primary,
            "regions": cambium["regions"],
            "fallback_region": "PJM_East",
            "fallback_region_limitation": "Pittsburgh project default only when a parcel lacks mappable county/state geography; not an inferred location-specific region.",
            "source_years": source_years,
            "scenarios": scenario_names,
            "emissions_components": {
                "source_unit": "kg CO2/MWh for CO2; g CH4 and N2O/MWh",
                "co2e_formula": "(CO2_direct + CO2_precombustion + GWP_CH4*(CH4_direct+CH4_precombustion)/1000 + GWP_N2O*(N2O_direct+N2O_precombustion)/1000) / 1000 = kgCO2e/kWh",
                "gwp": f"Cambium workbook GWP tab, 100-year AR6: CH4={cambium['gwp_ch4']}, N2O={cambium['gwp_n2o']}",
                "basis": "end-use demand; AER load includes imports/exports and average distribution losses",
            },
            "interpolation": "linear interpolation within each source scenario between Cambium five-year points",
            "post_2050": "No post-2050 data. Runtime exposes 2050 terminal scenario values and marks the carbon model's terminal-year hold explicitly.",
        },
    }


def _main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Refresh Lotline's offline carbon geography model.")
    parser.add_argument("--refresh", action="store_true", help="rebuild the compact checked-in model snapshot")
    parser.add_argument("--latch-csv", help="local official LATCH CSV; downloads from BTS if omitted")
    parser.add_argument("--cambium-xlsx", help="local Cambium 2024 workbook; downloads from NLR if omitted")
    parser.add_argument("--parcels-json", help="parcel index used to select direct tract rows")
    parser.add_argument("--output", help=f"output JSON path (default: {MODEL_PATH})")
    args = parser.parse_args()
    if not args.refresh:
        parser.error("--refresh is required; refresh may download official source files when local paths are omitted")
    print(json.dumps(refresh_model_data(args.latch_csv, args.cambium_xlsx, args.parcels_json, args.output), indent=2))


if __name__ == "__main__":
    _main()
