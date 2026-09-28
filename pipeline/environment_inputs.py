"""Offline parsers for environmental evidence tables.

These helpers consume source snapshots downloaded by the pipeline operator.
They do not fetch or redistribute third-party datasets implicitly.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from urllib.request import Request, urlopen

BTS_LATCH_2017_CSV = "https://data.transportation.gov/api/v3/views/va72-z8hz/export.csv?accessType=DOWNLOAD"


def read_latch_tract_vmt(
    rows: Iterable[dict[str, str]],
    tract_geoid: str,
    *,
    tract_field: str,
    weekday_vmt_field: str,
    profile: str,
    weekday_days_per_year: float | None = None,
    weekend_to_weekday_ratio: float | None = None,
    suppressed_field: str | None = None,
    source_id: str = "bts_latch_2017",
) -> dict | None:
    """Select a published LATCH weekday household VMT tract/profile row.

    Annualization is only performed when both an explicit weekday count and
    weekend-to-weekday ratio are supplied. Otherwise the output stays in
    weekday miles/day and cannot be mistaken for annual household VMT.
    """
    target = normalize_tract_geoid(tract_geoid)
    for row in rows:
        if normalize_tract_geoid(row.get(tract_field, "")) != target:
            continue
        raw = row.get(weekday_vmt_field)
        suppression = row.get(suppressed_field, "") if suppressed_field else ""
        if suppression and str(suppression).strip().lower() not in {"0", "false", "no", "none"}:
            return _latch_suppressed(profile, target, source_id, str(suppression))
        try:
            weekday = float(raw)  # suppressions and blanks are not numbers
        except (TypeError, ValueError):
            return _latch_suppressed(profile, target, source_id, "missing or nonnumeric VMT")
        if weekday_days_per_year is None or weekend_to_weekday_ratio is None:
            return {
                "value": weekday, "low": weekday, "high": weekday,
                "unit": "vehicle miles/household/weekday",
                "provenance": "modeled", "evidence_tier": "geographic_estimate",
                "interval_type": "point_estimate", "geography": f"2010 tract {target}",
                "source_ids": [source_id], "as_of": 2017,
                "profile": profile,
                "limitations": "BTS LATCH modeled average weekday value; no annualization or household-specific inference.",
                "confirmation_needed": "Select a household profile and validate weekend annualization against matching NHTS observations",
            }
        if weekday_days_per_year <= 0 or weekend_to_weekday_ratio < 0:
            raise ValueError("annualization factors must be nonnegative and weekday days must be positive")
        annual = weekday * (weekday_days_per_year + (365 - weekday_days_per_year) * weekend_to_weekday_ratio)
        return {
            "value": annual, "low": annual, "high": annual,
            "unit": "vehicle miles/household/year",
            "provenance": "modeled", "evidence_tier": "geographic_estimate",
            "interval_type": "point_estimate", "geography": f"2010 tract {target}",
            "source_ids": [source_id], "as_of": 2017, "profile": profile,
            "annualization": {
                "weekday_days_per_year": weekday_days_per_year,
                "weekend_to_weekday_ratio": weekend_to_weekday_ratio,
                "formula": "weekday_vmt * (weekday_days + weekend_days * weekend_to_weekday_ratio)",
            },
            "limitations": "BTS LATCH modeled average weekday tract/profile estimate annualized with explicit external factors; not parcel- or household-specific.",
            "confirmation_needed": "Validate annualization against matching NHTS observations and retain LATCH suppression/imprecision flags",
        }
    return None


def load_csv(path: str | Path, *, encoding: str = "utf-8-sig") -> list[dict[str, str]]:
    """Read a source snapshot without changing field names or suppression codes."""
    with Path(path).open(newline="", encoding=encoding) as stream:
        return list(csv.DictReader(stream))


def download_latch_snapshot(output_path: str | Path) -> dict:
    """Download the public BTS LATCH 2017 CSV and return a reproducibility record."""
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    request = Request(BTS_LATCH_2017_CSV, headers={"User-Agent": "Lotline evidence pipeline/1.0"})
    digest = hashlib.sha256()
    size = 0
    with urlopen(request, timeout=60) as response, path.open("wb") as output:
        final_url = response.geturl()
        if not final_url.startswith("https://"):
            raise ValueError("BTS snapshot redirected to a non-HTTPS URL")
        while chunk := response.read(1024 * 1024):
            output.write(chunk)
            digest.update(chunk)
            size += len(chunk)
    return {
        "source_id": "bts_latch_2017", "url": BTS_LATCH_2017_CSV,
        "final_url": final_url, "retrieved_at": datetime.now(UTC).isoformat(),
        "path": str(path), "size_bytes": size, "sha256": digest.hexdigest(),
    }


def build_latch_tract_index(
    rows: Iterable[dict[str, str]], *, tract_field: str, weekday_vmt_field: str,
    profile: str, weekday_days_per_year: float | None = None,
    weekend_to_weekday_ratio: float | None = None, suppressed_field: str | None = None,
    source_id: str = "bts_latch_2017",
) -> dict[str, dict]:
    """Build a tract-to-envelope index once for an efficient citywide parcel join."""
    grouped: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        geoid = normalize_tract_geoid(row.get(tract_field, ""))
        if geoid.strip("0"):
            grouped.setdefault(geoid, []).append(row)
    result = {}
    for geoid, tract_rows in grouped.items():
        envelope = read_latch_tract_vmt(
            tract_rows, geoid, tract_field=tract_field,
            weekday_vmt_field=weekday_vmt_field, profile=profile,
            weekday_days_per_year=weekday_days_per_year,
            weekend_to_weekday_ratio=weekend_to_weekday_ratio,
            suppressed_field=suppressed_field, source_id=source_id,
        )
        if envelope is not None:
            result[geoid] = envelope
    return result


def latch_envelope_for_parcel(parcel: dict, tract_index: dict[str, dict], *, tract_field: str = "tract_2010") -> dict:
    """Join a parcel's 2010 tract to LATCH while making missing geography explicit."""
    geoid = normalize_tract_geoid(parcel.get(tract_field, ""))
    envelope = tract_index.get(geoid)
    if envelope is not None:
        return envelope
    return {
        "value": None, "low": None, "high": None, "unit": "vehicle miles/household/year",
        "provenance": "placeholder", "evidence_tier": "unresolved_geography_or_source_value",
        "interval_type": "none", "geography": f"2010 tract {geoid}" if geoid.strip("0") else "missing 2010 tract",
        "source_ids": ["bts_latch_2017"], "as_of": 2017,
        "limitations": "No matched, usable BTS LATCH estimate is available for this parcel's 2010 tract and selected profile.",
        "confirmation_needed": "Verify 2010 tract join or use a declared travel scenario with its uncertainty shown",
    }


def attach_latch_to_parcel_evidence(records: Iterable[dict], tract_index: dict[str, dict]) -> list[dict]:
    """Attach LATCH envelopes to parcel-evidence rows without dropping records."""
    joined = []
    for row in records:
        result = dict(row)
        parcel = result.get("parcel") or {}
        evidence = dict(result.get("evidence") or {})
        evidence["vmt_per_household_yr"] = latch_envelope_for_parcel(parcel, tract_index)
        result["evidence"] = evidence
        joined.append(result)
    return joined


def normalize_tract_geoid(value: object) -> str:
    """Normalize common tract identifier forms while retaining 11-digit FIPS."""
    text = "".join(ch for ch in str(value) if ch.isdigit())
    if len(text) > 11:
        text = text[-11:]
    if len(text) < 11:
        text = text.zfill(11)
    return text


def build_annual_grid_path(
    rows: Iterable[dict[str, str]], *, region: str, scenario: str,
    year_field: str, region_field: str, scenario_field: str,
    emissions_field: str, unit: str, source_id: str = "nrel_cambium",
    series: str = "average",
) -> dict | None:
    """Select a named annual regional grid series without extrapolation.

    ``unit`` must be ``kg/MWh``, ``lb/MWh``, or ``kg/kWh``. Marginal output is
    retained as marginal and must not be used as a footprint-average series.
    """
    if series not in {"average", "marginal"}:
        raise ValueError("series must be average or marginal")
    if unit not in {"kg/MWh", "lb/MWh", "kg/kWh"}:
        raise ValueError(f"unsupported grid emissions unit: {unit}")
    selected = [row for row in rows if row.get(region_field) == region and row.get(scenario_field) == scenario]
    selected.sort(key=lambda row: int(row[year_field]))
    if not selected:
        return None
    factor = {"kg/MWh": 0.001, "lb/MWh": 0.00045359237, "kg/kWh": 1.0}[unit]
    years, values = [], []
    for row in selected:
        try:
            year, value = int(row[year_field]), float(row[emissions_field])
        except (TypeError, ValueError, KeyError):
            continue
        if value < 0:
            raise ValueError("negative annual grid emissions rate is invalid")
        years.append(year)
        values.append(value * factor)
    if not years:
        return None
    if len(set(years)) != len(years):
        raise ValueError(f"duplicate annual grid rows for {region} / {scenario}")
    return {
        "value": values, "low": values, "high": values,
        "unit": "kgCO2e/kWh by year", "provenance": "modeled",
        "evidence_tier": "regional_scenario", "interval_type": "scenario_trajectory",
        "geography": region, "source_ids": [source_id], "as_of": years[-1],
        "model_id": f"cambium:{scenario}:{series}", "years": years, "series": series,
        "limitations": "Selected annual regional scenario series; no extrapolation or interpolation. The trajectory ends at its last modeled year.",
        "confirmation_needed": "Verify regional mapping and scenario choice; compare the base year with EPA eGRID",
    }


def embodied_carbon_from_schedule(
    quantities: Iterable[dict[str, str]], factors: Iterable[dict[str, str]],
    *, typology_id: str, quantity_material_field: str = "material",
    quantity_per_sf_field: str = "quantity_per_sf", factor_material_field: str = "material",
    factor_value_field: str = "kgco2e_per_unit", stage_field: str = "stage",
    factor_low_field: str = "low", factor_high_field: str = "high",
    source_field: str = "source_id",
) -> dict | None:
    """Multiply declared per-sf material quantities by stage-specific EPD/LCI factors.

    Rows without a matching factor are reported as missing and withheld from a
    complete total, so the returned number cannot silently omit a material.
    """
    factor_rows = list(factors)
    by_material: dict[str, list[dict[str, str]]] = {}
    for factor in factor_rows:
        by_material.setdefault(factor.get(factor_material_field, ""), []).append(factor)
    stage_totals: dict[str, dict[str, float]] = {}
    source_ids: set[str] = set()
    missing: list[str] = []
    for item in quantities:
        material = item.get(quantity_material_field, "")
        try:
            amount = float(item[quantity_per_sf_field])
        except (TypeError, ValueError, KeyError):
            missing.append(material or "unnamed material: quantity unavailable")
            continue
        candidates = by_material.get(material, [])
        if not candidates:
            missing.append(material or "unnamed material: factor unavailable")
            continue
        for factor in candidates:
            stage = factor.get(stage_field, "unspecified")
            try:
                center = float(factor[factor_value_field])
                low = float(factor.get(factor_low_field, center))
                high = float(factor.get(factor_high_field, center))
            except (TypeError, ValueError, KeyError):
                missing.append(f"{material}/{stage}: factor unavailable")
                continue
            bucket = stage_totals.setdefault(stage, {"value": 0.0, "low": 0.0, "high": 0.0})
            bucket["value"] += amount * center
            bucket["low"] += amount * min(low, high)
            bucket["high"] += amount * max(low, high)
            if factor.get(source_field):
                source_ids.add(factor[source_field])
    if not stage_totals:
        return None
    complete = not missing
    total = {key: sum(stage[key] for stage in stage_totals.values()) for key in ("value", "low", "high")}
    return {
        "value": total["value"] if complete else None,
        "low": total["low"] if complete else None,
        "high": total["high"] if complete else None,
        "partial_value_kgco2e_sf": total["value"], "unit": "kgCO2e/sf", "provenance": "modeled",
        "evidence_tier": "declared_material_quantity_scenario", "interval_type": "scenario_range",
        "geography": f"{typology_id} prototype", "source_ids": sorted(source_ids),
        "as_of": None, "model_id": f"material_schedule:{typology_id}",
        "stage_totals_kgco2e_sf": stage_totals,
        "complete": complete, "missing_materials": sorted(set(missing)),
        "limitations": "Prototype bill of quantities multiplied by supplied stage-specific EPD/LCI factors; not design-specific." +
                       (" One or more material quantities or factors are missing, so the total is incomplete." if not complete else ""),
        "confirmation_needed": "Design-specific bill of quantities and licensed/appropriate EPD or LCI factors",
    }


def _main() -> None:
    parser = argparse.ArgumentParser(description="Download and normalize Lotline environmental source snapshots")
    commands = parser.add_subparsers(dest="command", required=True)
    download = commands.add_parser("download-latch", help="download the official BTS LATCH 2017 CSV")
    download.add_argument("--out", required=True, help="snapshot output path under data/raw")
    index = commands.add_parser("latch-index", help="build a tract envelope index from a downloaded snapshot")
    index.add_argument("--input", required=True)
    index.add_argument("--out", required=True)
    index.add_argument("--tract-field", required=True)
    index.add_argument("--weekday-vmt-field", required=True)
    index.add_argument("--profile", required=True)
    index.add_argument("--suppressed-field")
    index.add_argument("--weekday-days", type=float)
    index.add_argument("--weekend-ratio", type=float)
    join = commands.add_parser("join-latch", help="attach tract VMT envelopes to parcel evidence JSONL")
    join.add_argument("--parcels", required=True)
    join.add_argument("--index", required=True)
    join.add_argument("--out", required=True)
    args = parser.parse_args()
    if args.command == "download-latch":
        manifest = download_latch_snapshot(args.out)
        manifest_path = Path(args.out).with_suffix(Path(args.out).suffix + ".manifest.json")
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(manifest, indent=2))
    elif args.command == "latch-index":
        rows = load_csv(args.input)
        index_rows = build_latch_tract_index(
            rows, tract_field=args.tract_field, weekday_vmt_field=args.weekday_vmt_field,
            profile=args.profile, suppressed_field=args.suppressed_field,
            weekday_days_per_year=args.weekday_days,
            weekend_to_weekday_ratio=args.weekend_ratio,
        )
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(json.dumps(index_rows, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"tract_count": len(index_rows), "output": args.out}, indent=2))
    elif args.command == "join-latch":
        index_rows = json.loads(Path(args.index).read_text(encoding="utf-8"))
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        count = 0
        with Path(args.parcels).open(encoding="utf-8") as source, Path(args.out).open("w", encoding="utf-8") as target:
            for line in source:
                if not line.strip():
                    continue
                row = json.loads(line)
                joined = attach_latch_to_parcel_evidence([row], index_rows)[0]
                target.write(json.dumps(joined, sort_keys=True) + "\n")
                count += 1
        print(json.dumps({"parcel_records_preserved": count, "output": args.out}, indent=2))


if __name__ == "__main__":
    _main()


def _latch_suppressed(profile: str, geoid: str, source_id: str, reason: str) -> dict:
    return {
        "value": None, "low": None, "high": None,
        "unit": "vehicle miles/household/year", "provenance": "placeholder",
        "evidence_tier": "unresolved_source_value", "interval_type": "none",
        "geography": f"2010 tract {geoid}", "source_ids": [source_id], "as_of": 2017,
        "profile": profile, "limitations": f"LATCH value unavailable: {reason}.",
        "confirmation_needed": "Retain suppression/imprecision flag; use explicit scenario or obtain suitable regional travel-model output",
    }
