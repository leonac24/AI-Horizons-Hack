"""Join public tract and polygon context to the existing vacant-lot index.

Run ``python -m pipeline.enrich_context`` to refresh the checked-in index without
re-fetching county assessments. ``build_parcels`` also calls ``enrich_records``.
Large source geometries live only in gitignored data/raw; the published record
contains the resulting site facts and the method used to join them.
"""

from __future__ import annotations

import json
import logging
from collections import Counter
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import TYPE_CHECKING

from core.config import ROOT, Config, load_config

if TYPE_CHECKING:
    import geopandas as gpd

log = logging.getLogger("pipeline.context")
RAW = ROOT / "data" / "raw"
PROCESSED = ROOT / "data" / "processed"
PARCEL_CONTEXT_FIELDS = (
    "geometry_frontage_ft",
    "geometry_depth_ft",
    "geometry_dimensions_method",
    "transit_access_index",
    "transit_jobs_accessible",
)
RENTER_INCOME_BINS = (
    (15, 0, 5_000, "less than $5,000"),
    (16, 5_000, 10_000, "$5,000 to $9,999"),
    (17, 10_000, 15_000, "$10,000 to $14,999"),
    (18, 15_000, 20_000, "$15,000 to $19,999"),
    (19, 20_000, 25_000, "$20,000 to $24,999"),
    (20, 25_000, 35_000, "$25,000 to $34,999"),
    (21, 35_000, 50_000, "$35,000 to $49,999"),
    (22, 50_000, 75_000, "$50,000 to $74,999"),
    (23, 75_000, 100_000, "$75,000 to $99,999"),
    (24, 100_000, 150_000, "$100,000 to $149,999"),
    (25, 150_000, None, "$150,000 or more"),
)


def _write_parcel_context(records: list[dict]) -> None:
    """Write supplementary geometry/transit values separately from the parcel index."""
    context = {}
    for record in records:
        values = {
            key: record.get(key) for key in PARCEL_CONTEXT_FIELDS if record.get(key) is not None
        }
        if values:
            context[record["id"]] = values
    PROCESSED.mkdir(parents=True, exist_ok=True)
    lines = (
        json.dumps({"id": parcel_id, **values}, separators=(",", ":"), sort_keys=True)
        for parcel_id, values in sorted(context.items())
    )
    (PROCESSED / "parcel_context.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _strip_parcel_context(records: list[dict]) -> None:
    for record in records:
        for key in PARCEL_CONTEXT_FIELDS:
            record.pop(key, None)


def _positive_number(value: str | None) -> int | None:
    try:
        number = int(value)  # Census negative sentinels mean unavailable.
        return number if number >= 0 else None
    except (TypeError, ValueError):
        return None


def _acs_table(url: str, county_geoid: str, name: str) -> dict[str, dict]:
    import requests

    cache = RAW / f"{name}_{county_geoid}_{sha256(url.encode()).hexdigest()[:12]}.json"
    if cache.exists():
        return json.loads(cache.read_text(encoding="utf-8"))
    rows: dict[str, dict] = {}
    with requests.get(url, stream=True, timeout=180) as response:
        response.raise_for_status()
        lines = response.iter_lines()
        header = next(lines).decode().split("|")
        if header[0] != "GEO_ID":
            raise ValueError(f"unexpected ACS table header at {url}")
        prefix = f"1400000US{county_geoid}"
        for line in lines:
            if line.startswith((prefix.encode(), f"0500000US{county_geoid}".encode())):
                cells = line.decode().split("|")
                if len(cells) != len(header):
                    raise ValueError(f"incomplete ACS row in {url}")
                geoid = cells[0][-11:] if cells[0].startswith(prefix) else county_geoid
                rows[geoid] = dict(zip(header[1:], cells[1:]))
    if not rows:
        raise ValueError(f"no tract rows for {county_geoid} in {url}")
    RAW.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(rows, separators=(",", ":")), encoding="utf-8")
    return rows


def _tract_values(income: dict[str, dict], burden: dict[str, dict]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for geoid in income.keys() | burden.keys():
        value: dict = {}
        i = income.get(geoid, {})
        median = _positive_number(i.get("B19013_E001"))
        moe = _positive_number(i.get("B19013_M001"))
        if median is not None:
            value["tract_median_household_income"] = median
            value["tract_median_household_income_moe"] = moe
        b = burden.get(geoid, {})
        total = _positive_number(b.get("B25070_E001"))
        not_computed = _positive_number(b.get("B25070_E011"))
        counts = [_positive_number(b.get(f"B25070_E{k:03d}")) for k in range(7, 11)]
        if total is not None and not_computed is not None and all(x is not None for x in counts):
            denominator = total - not_computed
            numerator = sum(counts)
            if denominator > 0 and numerator <= denominator:
                value["tract_renter_cost_burden_share"] = round(numerator / denominator, 5)
                value["tract_renter_cost_burden_numerator"] = numerator
                value["tract_renter_cost_burden_denominator"] = denominator
                # Conservative component-MOE envelope, not a published ratio MOE.
                num_moes = [_positive_number(b.get(f"B25070_M{k:03d}")) for k in range(7, 11)]
                den_moes = [_positive_number(b.get(f"B25070_M{k:03d}")) for k in (1, 11)]
                if all(x is not None for x in num_moes + den_moes):
                    nm, dm = sum(num_moes), sum(den_moes)
                    value["tract_renter_cost_burden_low"] = round(
                        max(0, numerator - nm) / (denominator + dm), 5
                    )
                    value["tract_renter_cost_burden_high"] = round(
                        min(1, (numerator + nm) / max(1, denominator - dm)), 5
                    )
        out[geoid] = value
    return out


def _renter_income_values(rows: dict[str, dict]) -> dict[str, dict]:
    """Extract ACS B25118 renter household bins with their published 90% MOEs."""
    out: dict[str, dict] = {}
    for geoid, row in rows.items():
        bins = []
        valid = True
        for index, low, high, label in RENTER_INCOME_BINS:
            count = _positive_number(row.get(f"B25118_E{index:03d}"))
            moe = _positive_number(row.get(f"B25118_M{index:03d}"))
            if count is None:
                valid = False
                break
            bins.append(
                {
                    "lower_usd": low,
                    "upper_usd": high,
                    "label": label,
                    "households": count,
                    "moe_90": moe,
                }
            )
        total = _positive_number(row.get("B25118_E014"))
        total_moe = _positive_number(row.get("B25118_M014"))
        if valid and total is not None and sum(item["households"] for item in bins) <= total:
            out[geoid] = {"total_renter_households": total, "total_moe_90": total_moe, "bins": bins}
    return out


def _arcgis_geojson(url: str, params: dict) -> dict:
    import requests

    response = requests.get(f"{url}/query", params=params, timeout=120)
    response.raise_for_status()
    result = response.json()
    if "error" in result:
        raise ValueError(f"ArcGIS query failed: {result['error']}")
    return result


def _parcel_polygons(spec: dict, ids: list[str]) -> dict[str, dict]:
    import requests

    cache = RAW / "context_parcel_polygons.geojson"
    features = (
        json.loads(cache.read_text(encoding="utf-8")).get("features", []) if cache.exists() else []
    )
    by_id = {f["properties"]["PIN"]: f for f in features if f.get("properties", {}).get("PIN")}
    missing = [pid for pid in ids if pid not in by_id]
    if missing:
        for offset in range(0, len(missing), 100):
            batch = missing[offset : offset + 100]
            quoted = ",".join(f"'{pid}'" for pid in batch)
            try:
                result = _arcgis_geojson(
                    spec["service_url"],
                    {
                        "f": "geojson",
                        "where": f"PIN IN ({quoted})",
                        "outFields": "PIN",
                        "outSR": "4326",
                        "returnGeometry": "true",
                        "geometryPrecision": 7,
                    },
                )
            except (requests.RequestException, OSError, ValueError, KeyError, TypeError) as exc:
                log.warning(
                    "county parcel polygon query stopped at %d/%d (%s)",
                    offset,
                    len(missing),
                    type(exc).__name__,
                )
                break
            for f in result.get("features", []):
                pid = f.get("properties", {}).get("PIN")
                if pid in batch and f.get("geometry"):
                    by_id[pid] = f
            if offset % 2000 == 0:
                log.info(
                    "county parcel polygons: %d/%d requested", offset + len(batch), len(missing)
                )
        RAW.mkdir(parents=True, exist_ok=True)
        cache.write_text(
            json.dumps(
                {"type": "FeatureCollection", "features": list(by_id.values())},
                separators=(",", ":"),
            ),
            encoding="utf-8",
        )
    return {pid: by_id[pid] for pid in ids if pid in by_id}


def _address_point_locations(spec: dict, ids: list[str]) -> dict[str, tuple[float, float]]:
    import requests

    """Fetch county address points only for the remaining PINs; return lon/lat."""
    cache = RAW / "context_address_points.geojson"
    features = (
        json.loads(cache.read_text(encoding="utf-8")).get("features", []) if cache.exists() else []
    )
    by_id = {
        str(f.get("properties", {}).get("PARCELID")): f
        for f in features
        if f.get("properties", {}).get("PARCELID") and f.get("geometry")
    }
    missing = [str(pid) for pid in ids if str(pid) not in by_id]
    if missing:
        for offset in range(0, len(missing), 100):
            batch = missing[offset : offset + 100]
            quoted = ",".join(f"'{pid}'" for pid in batch)
            try:
                payload = _arcgis_geojson(
                    spec["service_url"],
                    {
                        "f": "geojson",
                        "where": f"PARCELID IN ({quoted})",
                        "outFields": "PARCELID",
                        "outSR": "4326",
                        "returnGeometry": "true",
                        "geometryPrecision": 7,
                    },
                )
            except (requests.RequestException, OSError, ValueError, KeyError, TypeError) as exc:
                log.warning(
                    "county address-point query stopped at %d/%d (%s)",
                    offset,
                    len(missing),
                    type(exc).__name__,
                )
                break
            for feature in payload.get("features", []):
                pid = str(feature.get("properties", {}).get("PARCELID") or "")
                if pid in batch and feature.get("geometry"):
                    by_id[pid] = feature
        RAW.mkdir(parents=True, exist_ok=True)
        cache.write_text(
            json.dumps(
                {"type": "FeatureCollection", "features": list(by_id.values())},
                separators=(",", ":"),
            ),
            encoding="utf-8",
        )
    locations = {}
    for pid in ids:
        feature = by_id.get(str(pid))
        if not feature:
            continue
        geometry = feature.get("geometry", {})
        if geometry.get("type") == "Point" and len(geometry.get("coordinates", [])) >= 2:
            lon, lat = geometry["coordinates"][:2]
            if -180 <= float(lon) <= 180 and -90 <= float(lat) <= 90:
                locations[str(pid)] = (float(lon), float(lat))
    return locations


def _normalize_sale_date(value: str | None) -> str | None:
    if not value:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw).date().isoformat()
    except ValueError:
        pass
    for pattern in ("%d/%m/%Y", "%m/%d/%Y"):
        try:
            return datetime.strptime(raw, pattern).replace(tzinfo=UTC).date().isoformat()
        except ValueError:
            continue
    return None


def _valid_single_parcel_sales(
    rows: list[dict],
    parcel_records: list[dict],
    source_id: str,
    snapshot_id: str,
    funnel_out: dict | None = None,
) -> list[dict]:
    """Filter valid positive-price deeds, excluding bundled/multiparcel deed groups."""
    import math

    deed_counts = Counter(
        (str(row.get("DEEDBOOK") or "").strip(), str(row.get("DEEDPAGE") or "").strip())
        for row in rows
        if str(row.get("DEEDBOOK") or "").strip() and str(row.get("DEEDPAGE") or "").strip()
    )
    parcels = {str(r["id"]): r for r in parcel_records}
    out, seen = [], set()
    funnel = Counter(raw_records=len(rows))
    for row in rows:
        pid = str(row.get("PARID") or "").strip()
        subject = parcels.get(pid)
        if not subject:
            continue
        funnel["parcel_id_overlap"] += 1
        desc = str(row.get("SALEDESC") or "").strip().casefold()
        if desc != "valid sale":
            continue
        funnel["valid_sale_code"] += 1
        deed = (str(row.get("DEEDBOOK") or "").strip(), str(row.get("DEEDPAGE") or "").strip())
        try:
            price = float(row.get("PRICE"))
        except (TypeError, ValueError):
            continue
        if not math.isfinite(price) or price <= 0:
            continue
        funnel["positive_price"] += 1
        if not all(deed) or deed_counts.get(deed) != 1 or (pid, deed) in seen:
            continue
        funnel["unique_single_parcel_deed"] += 1
        sale_date = _normalize_sale_date(row.get("SALEDATE"))
        if not sale_date:
            continue
        funnel["parseable_sale_date"] += 1
        try:
            area = float(subject.get("lot_area_sf"))
        except (TypeError, ValueError):
            continue
        if not math.isfinite(area) or area <= 0:
            continue
        funnel["positive_parcel_area"] += 1
        out.append(
            {
                "parcel_id": pid,
                "sale_price": round(price, 2),
                "sale_date": sale_date,
                "parcel_area_sqft": round(area, 1),
                "arm_length": True,
                "vacant": str(subject.get("land_use") or "").strip().casefold()
                in {
                    "vacant land",
                    "vacant commercial land",
                    "vacant industrial land",
                    ">10 acres vacant",
                },
                "source_id": source_id,
                "snapshot_id": snapshot_id,
                "geography": "parcel",
                "neighborhood": subject.get("neighborhood"),
                "zoning": subject.get("zoning"),
                "lon": subject.get("lon"),
                "lat": subject.get("lat"),
                "context_as_of": "current parcel record; not sale-date condition or zoning",
            }
        )
        seen.add((pid, deed))
    if funnel_out is not None:
        funnel_out.update(funnel)
    return sorted(out, key=lambda x: (x["parcel_id"], x["sale_date"], x["sale_price"]))


def _raw_sha256(path: Path | None) -> str | None:
    if path is None or not path.exists():
        return None
    digest = sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_parcel_evidence(
    records: list[dict],
    sales: list[dict],
    snapshots: dict[str, str | None],
    statuses: dict[str, dict],
) -> None:
    """Write the application contract: one parcel/evidence row per PIN."""
    evidence_path = PROCESSED / "parcel_evidence.jsonl"
    sales_by_pin: dict[str, list[dict]] = {}
    for sale in sales:
        sales_by_pin.setdefault(sale["parcel_id"], []).append(sale)
    lines = []
    for record in sorted(records, key=lambda row: str(row["id"])):
        evidence = {}
        bins = record.get("acs_renter_income_bins")
        if bins:
            geography = record.get("acs_renter_income_geography") or {
                "type": "tract",
                "geoid": str(record.get("tract") or ""),
            }
            snapshot_key = "acs_2024_b25118"
            evidence["acs_renter_income_bins"] = {
                "value": bins,
                "low": None,
                "high": None,
                "unit": "renter households by annual household income bin",
                "provenance": "modeled",
                "evidence_tier": "geographic_estimate",
                "interval_type": "ACS 90% margins of error per estimate",
                "geography": geography,
                "source_ids": ["acs_2024_b25118"],
                "source_snapshot_ids": [snapshots.get(snapshot_key)],
                "model_id": None,
                "model_version": None,
                "sample_size": bins.get("total_renter_households"),
                "as_of": "2020-2024 ACS 5-year; 2024 geography",
                "limitations": [
                    f"{geography.get('type', 'unknown').title()} household distribution is area context, not parcel residents.",
                    "Open-ended income bins cannot support within-bin interpolation.",
                ],
                "confirmation_needed": None,
            }
        pin_sales = sales_by_pin.get(str(record["id"]), [])
        if pin_sales:
            evidence["county_sales"] = {
                "value": pin_sales,
                "low": None,
                "high": None,
                "unit": "USD per recorded parcel sale",
                "provenance": "observed",
                "evidence_tier": "direct_parcel_fact",
                "interval_type": None,
                "geography": {"type": "parcel", "pin": str(record["id"])},
                "source_ids": ["allegheny_property_sales"],
                "source_snapshot_ids": [snapshots.get("allegheny_property_sales")],
                "model_id": None,
                "model_version": None,
                "sample_size": len(pin_sales),
                "as_of": max(sale["sale_date"] for sale in pin_sales),
                "limitations": [
                    "Historic transfer consideration, not a current asking or purchase price.",
                    "Current assessment vacancy class does not establish vacancy on sale date.",
                ],
                "confirmation_needed": "Verify deed and current acquisition terms before use.",
            }
        zero_fields = record.get("assessment_zero_fields") or []
        if zero_fields:
            evidence["county_assessment_zero_fields"] = {
                "value": {field: 0 for field in zero_fields},
                "low": None,
                "high": None,
                "unit": "county-reported assessment field values",
                "provenance": "observed",
                "evidence_tier": "direct_parcel_fact",
                "interval_type": None,
                "geography": {"type": "parcel", "pin": str(record["id"])},
                "source_ids": ["wprdc_assessments"],
                "source_snapshot_ids": [snapshots.get("wprdc_assessments")],
                "model_id": None,
                "model_version": None,
                "sample_size": None,
                "as_of": "current county assessment extract",
                "limitations": [
                    "Zero lot area is unusable as physical area and is emitted as null.",
                    "Zero FAIRMARKETLAND is a county assessment value, not an acquisition price; emitted as null.",
                ],
                "confirmation_needed": "Confirm the parcel area/value with County assessment records.",
            }
        # The companion parcels.json already carries the complete parcel row;
        # this compact artifact contains only data deltas and model evidence.
        lines.append(
            json.dumps(
                {"id": str(record["id"]), "parcel": {}, "evidence": evidence},
                separators=(",", ":"),
                sort_keys=True,
            )
        )
    PROCESSED.mkdir(parents=True, exist_ok=True)
    evidence_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    sales_path = PROCESSED / "valid_parcel_sales.jsonl"
    sales_path.write_text(
        "\n".join(json.dumps(sale, separators=(",", ":"), sort_keys=True) for sale in sales)
        + ("\n" if sales else ""),
        encoding="utf-8",
    )
    manifest_core = {
        "schema_version": "lotline.parcel-evidence.v1",
        "record_count": len(records),
        "source_snapshots": snapshots,
        "source_status": statuses,
        "source_registry_sha256": _raw_sha256(ROOT / "data" / "config" / "sources.yaml"),
        "artifact_sha256": {
            "parcel_evidence.jsonl": _raw_sha256(evidence_path),
            "valid_parcel_sales.jsonl": _raw_sha256(sales_path),
        },
    }
    manifest_core["source_manifest_hash"] = sha256(
        json.dumps(
            {
                "schema_version": manifest_core["schema_version"],
                "source_snapshots": snapshots,
                "source_status": statuses,
                "source_registry_sha256": manifest_core["source_registry_sha256"],
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    (PROCESSED / "parcel_evidence_manifest.json").write_text(
        json.dumps(manifest_core, indent=2, sort_keys=True), encoding="utf-8"
    )


def _sld_rows(spec: dict) -> list[dict]:
    """Fetch the Allegheny County block-group slice of EPA SLD 3.0."""
    import requests

    cache = RAW / "epa_smart_location_allegheny.json"
    if cache.exists():
        return json.loads(cache.read_text(encoding="utf-8"))["rows"]
    rows: list[dict] = []
    offset = 0
    while True:
        filters = spec["county_filter"]
        where = " AND ".join(f"{field}={int(value)}" for field, value in filters.items())
        response = requests.get(
            f"{spec['service_url']}/query",
            params={
                "where": where,
                "outFields": (
                    "OBJECTID,STATEFP,COUNTYFP,TRACTCE,BLKGRPCE,"
                    f"{spec['jobs_field']},{spec['index_field']}"
                ),
                "returnGeometry": "false",
                "resultRecordCount": 1000,
                "resultOffset": offset,
                "orderByFields": "OBJECTID",
                "f": "json",
            },
            timeout=90,
        )
        response.raise_for_status()
        payload = response.json()
        if "error" in payload:
            raise ValueError(f"EPA SLD query failed: {payload['error']}")
        features = payload.get("features", [])
        for feature in features:
            attrs = feature.get("attributes", {})
            try:
                geoid = (
                    f"{int(attrs['STATEFP']):02d}{int(attrs['COUNTYFP']):03d}"
                    f"{int(attrs['TRACTCE']):06d}{int(attrs['BLKGRPCE']):1d}"
                )
                jobs = float(attrs[spec["jobs_field"]])
                index = float(attrs[spec["index_field"]])
            except (KeyError, TypeError, ValueError):
                continue
            if len(geoid) == 12 and jobs >= 0 and 0 <= index <= 1:
                rows.append(
                    {
                        "block_group_geoid": geoid,
                        "jobs_accessible": jobs,
                        "transit_access_index": index,
                    }
                )
        if len(features) < 1000:
            break
        offset += len(features)
    if not rows:
        raise ValueError("EPA SLD query returned no valid Allegheny County block groups")
    RAW.mkdir(parents=True, exist_ok=True)
    cache.write_text(
        json.dumps(
            {"source": spec["source"], "vintage": "SLD 3.0 (2021)", "rows": rows},
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )
    return rows


def _transit_access(spec: dict, records: list[dict]) -> None:
    """Join SLD's 2020 block-group accessibility fields to parcel records."""
    by_geoid = {row["block_group_geoid"]: row for row in _sld_rows(spec)}
    for record in records:
        tract = str(record.get("tract") or "")
        block_group = str(record.get("block_group") or "")
        key = tract + block_group if len(tract) == 11 and len(block_group) == 1 else ""
        match = by_geoid.get(key)
        record["transit_access_index"] = match["transit_access_index"] if match else None
        record["transit_jobs_accessible"] = match["jobs_accessible"] if match else None


def _geometry_dimensions(records: list[dict], boundaries: dict[str, dict]) -> int:
    """Store modeled parcel axes where deed dimensions are unavailable."""
    from pyproj import Transformer
    from shapely.geometry import shape
    from shapely.ops import transform

    project = Transformer.from_crs(4326, 2272, always_xy=True).transform
    estimated = 0
    for record in records:
        if record.get("frontage_ft") and record.get("depth_ft"):
            continue
        feature = boundaries.get(record["id"])
        if not feature or not feature.get("geometry"):
            continue
        try:
            geom = shape(feature["geometry"])
        except (TypeError, ValueError):
            continue
        if geom.is_empty or geom.geom_type == "MultiPolygon":
            continue
        local = transform(project, geom)
        if not local.is_valid:
            local = local.buffer(0)
        if local.is_empty or local.area <= 0 or local.geom_type != "Polygon":
            continue
        rect = local.minimum_rotated_rectangle
        coords = list(rect.exterior.coords)
        lengths = [
            ((coords[i + 1][0] - coords[i][0]) ** 2 + (coords[i + 1][1] - coords[i][1]) ** 2) ** 0.5
            for i in range(4)
        ]
        lengths = sorted(x for x in lengths if x > 0)
        if len(lengths) != 4:
            continue
        frontage, depth = lengths[0], lengths[2]
        if not (5 <= frontage <= 1500 and 5 <= depth <= 3000):
            continue
        if rect.area / local.area > 2.0:
            continue
        record["geometry_frontage_ft"] = round(frontage, 1)
        record["geometry_depth_ft"] = round(depth, 1)
        record["geometry_dimensions_method"] = "minimum rotated rectangle; EPSG:2272 feet"
        estimated += 1
    return estimated


def _fema_polygons(spec: dict, records: list[dict]) -> gpd.GeoDataFrame:
    import geopandas as gpd

    cache = RAW / "context_fema_pittsburgh.geojson"
    if not cache.exists():
        located = [
            r
            for r in records
            if r.get("lon") is not None
            and r.get("lat") is not None
            and -180 <= float(r["lon"]) <= 180
            and -90 <= float(r["lat"]) <= 90
        ]
        if not located:
            raise ValueError("FEMA query has no valid parcel coordinates for an extent")
        lons = [float(r["lon"]) for r in located]
        lats = [float(r["lat"]) for r in located]
        envelope = f"{min(lons) - 0.01},{min(lats) - 0.01},{max(lons) + 0.01},{max(lats) + 0.01}"
        spatial = {
            "geometry": envelope,
            "geometryType": "esriGeometryEnvelope",
            "inSR": "4326",
            "spatialRel": "esriSpatialRelIntersects",
        }
        ids = (
            _arcgis_geojson(
                spec["service_url"],
                {
                    "f": "json",
                    "where": "1=1",
                    **spatial,
                    "returnIdsOnly": "true",
                },
            ).get("objectIds")
            or []
        )
        if not ids:
            raise ValueError("FEMA query returned no Pittsburgh polygons")
        features: list[dict] = []
        # PASDA's service returns HTTP 500 for some 100-feature geometry pages.
        # Small pages keep individual complex flood polygons below its limit.
        for offset in range(0, len(ids), 25):
            result = _arcgis_geojson(
                spec["service_url"],
                {
                    "f": "geojson",
                    "objectIds": ",".join(map(str, ids[offset : offset + 25])),
                    "outFields": "OBJECTID,FLD_ZONE,SFHA_TF,ZONE_SUBTY,SOURCE_CIT,VERSION_ID",
                    "outSR": "4326",
                    "returnGeometry": "true",
                    "geometryPrecision": 7,
                },
            )
            features.extend(result.get("features", []))
            if offset % 500 == 0:
                log.info("FEMA polygons: %d/%d requested", min(offset + 25, len(ids)), len(ids))
        if len(features) != len(ids):
            raise ValueError(f"FEMA returned {len(features)} of {len(ids)} polygons")
        RAW.mkdir(parents=True, exist_ok=True)
        cache.write_text(
            json.dumps({"type": "FeatureCollection", "features": features}, separators=(",", ":")),
            encoding="utf-8",
        )
    layer = gpd.read_file(cache).to_crs(4326)
    log.info("FEMA cache loaded: %d polygons", len(layer))
    return layer[layer.geometry.notna()].copy()


def _polygon_matches(
    records: list[dict], parcel_features: dict[str, dict], layer: gpd.GeoDataFrame, value_col: str
) -> dict[str, list[dict]]:
    """Screen at a point inside each parcel polygon, or its published centroid."""
    import geopandas as gpd
    from shapely.geometry import Point, shape

    rows = []
    for r in records:
        feature = parcel_features.get(r["id"])
        boundary = shape(feature["geometry"]) if feature else None
        if boundary is not None and not boundary.is_empty:
            point = boundary.representative_point()
            method = "point inside county parcel polygon"
        elif str(r.get("location_method") or "").startswith("PIN-matched county address point"):
            # The point keeps the PIN mappable, but may represent a nearby
            # structure and is not parcel geometry for zoning or hazard joins.
            continue
        else:
            if r.get("lon") is None or r.get("lat") is None:
                continue
            point = Point(r["lon"], r["lat"])
            method = "published parcel centroid (boundary unavailable)"
        rows.append({"id": r["id"], "geometry": point, "join_method": method})
    if not rows:
        return {}
    points = gpd.GeoDataFrame(rows, geometry="geometry", crs=4326)
    target = layer.to_crs(4326).copy()
    log.info(
        "%s: spatial join of %d parcel points to %d polygons", value_col, len(points), len(target)
    )
    matches: dict[str, list[dict]] = {}
    if not points.empty and not target.empty:
        hits = gpd.sjoin(points, target[[value_col, "geometry"]], how="inner", predicate="within")
        log.info("%s: %d point-in-polygon matches", value_col, len(hits))
        for row in hits.itertuples():
            matches.setdefault(row.id, []).append(
                {
                    "value": getattr(row, value_col),
                    "layer_index": row.index_right,
                    "join_method": row.join_method,
                }
            )
    return matches


def enrich_records(cfg: Config, records: list[dict], report: dict) -> None:
    import geopandas as gpd
    import requests

    from pipeline.adapters.ckan import CkanDownload

    specs = cfg.city.model_dump()["context"]
    counts = report.setdefault("counts", {})
    details = report.setdefault("context", {})
    county = cfg.city.state_fips + cfg.city.county_fips
    acs = specs["acs"]
    try:
        tracts = _tract_values(
            _acs_table(acs["income_url"], county, "acs_income"),
            _acs_table(acs["rent_burden_url"], county, "acs_rent_burden"),
        )
        for r in records:
            r.update(tracts.get(str(r.get("tract")), {}))
        details["acs"] = {
            "source": acs["source"],
            "status": "loaded",
            "join": "11-digit tract GEOID; 2024 ACS geography",
        }
    except (requests.RequestException, OSError, ValueError) as exc:
        details["acs"] = {"source": acs["source"], "status": "unavailable", "reason": str(exc)}
        log.warning("ACS context unavailable: %s", exc)
    counts["acs_income_values"] = sum(
        r.get("tract_median_household_income") is not None for r in records
    )
    counts["acs_renter_burden_values"] = sum(
        r.get("tract_renter_cost_burden_share") is not None for r in records
    )

    snapshot_ids: dict[str, str | None] = {}
    source_status: dict[str, dict] = {}
    for source_id, filename in {
        "wprdc_assessments": "wprdc_assessments.json",
        "allegheny_parcel_boundaries": "context_parcel_polygons.geojson",
        "allegheny_address_points": "context_address_points.geojson",
    }.items():
        path = RAW / filename
        if path.exists():
            snapshot_ids[source_id] = _raw_sha256(path)
            source_status[source_id] = {"status": "cached", "sha256": snapshot_ids[source_id]}
    b25118 = None
    try:
        b25118_rows = _acs_table(acs["renter_income_url"], county, "acs_b25118")
        b25118 = _renter_income_values(b25118_rows)
        for record in records:
            record["acs_renter_income_bins"] = b25118.get(str(record.get("tract")))
        b25118_cache = (
            RAW
            / f"acs_b25118_{county}_{sha256(acs['renter_income_url'].encode()).hexdigest()[:12]}.json"
        )
        snapshot_ids["acs_2024_b25118"] = _raw_sha256(b25118_cache)
        source_status["acs_2024_b25118"] = {"status": "loaded", "matched_tracts": len(b25118)}
        details["acs_renter_income"] = {
            "source": "acs_2024_b25118",
            "status": "loaded",
            "join": "11-digit tract GEOID; B25118 renter-occupied income bins",
            "vintage": "2020-2024 ACS 5-year; 2024 tract geography",
        }
    except (requests.RequestException, OSError, ValueError, KeyError) as exc:
        for record in records:
            record["acs_renter_income_bins"] = None
        details["acs_renter_income"] = {
            "source": "acs_2024_b25118",
            "status": "unavailable",
            "reason": str(exc),
        }
        source_status["acs_2024_b25118"] = {"status": "unavailable", "reason": str(exc)}
        log.warning("ACS B25118 unavailable: %s", exc)
    for record in records:
        if record.get("acs_renter_income_bins") is not None:
            record["acs_renter_income_geography"] = {
                "type": "tract",
                "geoid": str(record.get("tract")),
            }
    missing_bins = [record for record in records if record.get("acs_renter_income_bins") is None]
    county_renter_bins = (b25118 or {}).get(cfg.city.state_fips + cfg.city.county_fips)
    if missing_bins:
        if county_renter_bins is not None:
            for record in missing_bins:
                record["acs_renter_income_bins"] = county_renter_bins
                record["acs_renter_income_geography"] = {
                    "type": "county",
                    "geoid": cfg.city.state_fips + cfg.city.county_fips,
                }
            details["acs_renter_income_fallback"] = {
                "status": "loaded",
                "geography": "county",
                "filled_records": len(missing_bins),
                "reason": "tract estimate unavailable or suppressed; county context substituted",
            }
        else:
            details["acs_renter_income_fallback"] = {
                "status": "unavailable",
                "reason": "tract estimate unavailable and county B25118 row absent or suppressed",
            }
            log.warning("ACS county B25118 fallback unavailable or suppressed")
    counts["acs_renter_income_bin_tracts"] = len(
        {
            record.get("acs_renter_income_geography", {}).get("geoid")
            for record in records
            if record.get("acs_renter_income_bins") is not None
            and record.get("acs_renter_income_geography", {}).get("type") == "tract"
        }
    )
    counts["acs_renter_income_bin_records"] = sum(
        record.get("acs_renter_income_bins") is not None for record in records
    )
    counts["acs_renter_income_bin_county_fallbacks"] = sum(
        record.get("acs_renter_income_geography", {}).get("type") == "county" for record in records
    )
    for table_name, url in (
        ("acs_income", acs["income_url"]),
        ("acs_rent_burden", acs["rent_burden_url"]),
    ):
        path = RAW / f"{table_name}_{county}_{sha256(url.encode()).hexdigest()[:12]}.json"
        if path.exists():
            snapshot_ids["acs_5yr"] = _raw_sha256(path)
            break

    try:
        boundaries = _parcel_polygons(specs["parcel_boundaries"], [r["id"] for r in records])
    except (requests.RequestException, OSError, ValueError) as exc:
        boundaries = {}
        details["parcel_boundaries"] = {"status": "unavailable", "reason": str(exc)}
        log.warning("parcel polygons unavailable: %s", exc)
    counts["parcel_polygons_matched"] = len(boundaries)
    source_status["allegheny_parcel_boundaries"] = {
        "status": "loaded" if len(boundaries) == len(records) else "partial",
        "matched_parcels": len(boundaries),
        "unmatched_parcels": len(records) - len(boundaries),
        "sha256": snapshot_ids.get("allegheny_parcel_boundaries"),
    }
    address_matched = sum(
        str(r.get("location_method") or "").startswith("PIN-matched county address point")
        for r in records
    )
    source_status["allegheny_address_points"] = {
        "status": "loaded" if address_matched else "not_needed_or_no_matches",
        "matched_parcels": address_matched,
        "sha256": snapshot_ids.get("allegheny_address_points"),
    }
    counts["geometry_dimensions_estimated"] = _geometry_dimensions(records, boundaries)
    transit = specs["transit_jobs"]
    try:
        _transit_access(transit, records)
        details["transit_jobs"] = {
            "source": transit["source"],
            "status": "loaded",
            "vintage": "EPA Smart Location Database 3.0 (2021); 2020 GTFS and travel times; 2017 LEHD",
            "join": "2020 block-group GEOID20 reconstructed from state, county, tract and group fields",
            "measure": "D5DRI relative transit jobs accessibility index and D5BR distance-decay-weighted jobs",
        }
    except (requests.RequestException, OSError, ValueError, KeyError) as exc:
        details["transit_jobs"] = {
            "source": transit["source"],
            "status": "unavailable",
            "reason": str(exc),
        }
        log.warning("EPA transit access unavailable: %s", exc)
        for record in records:
            record["transit_access_index"] = record["transit_jobs_accessible"] = None
    counts["transit_access_matched"] = sum(
        record.get("transit_access_index") is not None for record in records
    )

    flood = specs["flood"]
    try:
        fema = _fema_polygons(flood, records)
        hits = _polygon_matches(records, boundaries, fema, "FLD_ZONE")
        for r in records:
            found = hits.get(r["id"], [])
            if found:
                r["fema_flood_zones"] = sorted({str(h["value"]) for h in found if h["value"]})
                r["fema_sfha"] = any(
                    str(fema.loc[h["layer_index"], "SFHA_TF"]).upper() == "T" for h in found
                )
                r["fema_join_method"] = found[0]["join_method"]
            else:
                r["fema_flood_zones"] = None
                r["fema_sfha"] = None
                r["fema_join_method"] = None
        details["flood"] = {
            "source": flood["source"],
            "status": "loaded",
            "polygons": len(fema),
            "join": "parcel interior point; centroid fallback",
        }
    except (requests.RequestException, OSError, ValueError) as exc:
        details["flood"] = {"source": flood["source"], "status": "unavailable", "reason": str(exc)}
        log.warning("FEMA context unavailable: %s", exc)
        for r in records:
            r["fema_flood_zones"] = r["fema_sfha"] = r["fema_join_method"] = None
    counts["fema_classified"] = sum(r["fema_sfha"] is not None for r in records)
    counts["fema_sfha_flagged"] = sum(r["fema_sfha"] is True for r in records)

    sewershed = specs["combined_sewersheds"]
    try:
        fetched = CkanDownload(sewershed["source"]).fetch(cfg)
        if not fetched.ok:
            raise ValueError(fetched.notes)
        layer = gpd.read_file(fetched.data).to_crs(4326)
        hits = _polygon_matches(records, boundaries, layer, "CSO_SHED")
        for r in records:
            found = hits.get(r["id"], [])
            r["combined_sewershed_ids"] = (
                sorted({str(h["value"]) for h in found if h["value"]}) or None
            )
            r["sewershed_join_method"] = found[0]["join_method"] if found else None
        details["combined_sewersheds"] = {
            "source": sewershed["source"],
            "status": "loaded",
            "polygons": len(layer),
            "join": "parcel interior point; centroid fallback",
        }
    except (requests.RequestException, OSError, ValueError) as exc:
        details["combined_sewersheds"] = {
            "source": sewershed["source"],
            "status": "unavailable",
            "reason": str(exc),
        }
        log.warning("combined sewersheds unavailable: %s", exc)
        for r in records:
            r["combined_sewershed_ids"] = r["sewershed_join_method"] = None
    counts["combined_sewershed_matched"] = sum(
        r["combined_sewershed_ids"] is not None for r in records
    )
    details["generated_at_utc"] = datetime.now(UTC).isoformat()
    details["join_methods"] = dict(Counter(r["fema_join_method"] or "unmatched" for r in records))

    # County transactions are direct historical observations only after the
    # County's valid code and a unique deed-page check. Never use assessment
    # FAIRMARKETLAND as a sale-price substitute.
    sale_fields = [
        "PARID",
        "RECORDDATE",
        "SALEDATE",
        "PRICE",
        "DEEDBOOK",
        "DEEDPAGE",
        "SALECODE",
        "SALEDESC",
        "INSTRTYP",
        "INSTRTYPDESC",
    ]
    sale_source_id = "allegheny_property_sales"
    sale_cache = RAW / f"{sale_source_id}.json"
    sales: list[dict] = []
    try:
        from pipeline.adapters.ckan import CkanDatastore

        fetched_sales = CkanDatastore(sale_source_id, sale_fields).fetch(cfg)
        if not fetched_sales.ok:
            raise ValueError(fetched_sales.notes)
        snapshot_id = _raw_sha256(sale_cache)
        sales_funnel = {}
        sales = _valid_single_parcel_sales(
            fetched_sales.data,
            records,
            sale_source_id,
            snapshot_id or "missing-snapshot-hash",
            sales_funnel,
        )
        snapshot_ids[sale_source_id] = snapshot_id
        source_status[sale_source_id] = {
            "status": "loaded",
            "valid_single_parcel_rows": len(sales),
            "funnel": sales_funnel,
        }
        details["county_sales"] = {
            "source": sale_source_id,
            "status": "loaded",
            "valid_single_parcel_rows": len(sales),
            "funnel": sales_funnel,
            "filter": "SALEDESC=Valid Sale, positive price, valid date, one parcel per deed book/page",
            "limitations": [
                "Historical consideration is not a current asking price.",
                "Current assessment vacancy class does not establish sale-date condition.",
            ],
        }
    except (requests.RequestException, OSError, ValueError, KeyError) as exc:
        source_status[sale_source_id] = {"status": "unavailable", "reason": str(exc)}
        details["county_sales"] = {
            "source": sale_source_id,
            "status": "unavailable",
            "reason": str(exc),
        }
        log.warning("County sale records unavailable: %s", exc)
    counts["county_valid_single_parcel_sales"] = len(sales)
    _write_parcel_evidence(records, sales, snapshot_ids, source_status)


def main() -> None:
    cfg = load_config()
    index_path = PROCESSED / "parcels.json"
    payload = json.loads(index_path.read_text(encoding="utf-8"))
    report_path = PROCESSED / "pipeline_report.json"
    report = (
        json.loads(report_path.read_text(encoding="utf-8"))
        if report_path.exists()
        else {"counts": {}}
    )
    records = list(payload["parcels"].values())
    enrich_records(cfg, records, report)
    _write_parcel_context(records)
    _strip_parcel_context(records)
    payload["config_hash"] = cfg.hash
    index_path.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
    report["config_hash"] = cfg.hash
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    points_path = ROOT / "web" / "public" / "data" / "parcels.geojson"
    points = json.loads(points_path.read_text(encoding="utf-8"))
    for feat in points["features"]:
        r = payload["parcels"].get(feat["properties"]["id"])
        if r:
            feat["properties"]["fh"] = None if r["fema_sfha"] is None else int(r["fema_sfha"])
    points_path.write_text(json.dumps(points, separators=(",", ":")), encoding="utf-8")
    log.info("context coverage: %s", json.dumps(report["counts"]))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    main()
