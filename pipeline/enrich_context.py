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
from typing import TYPE_CHECKING

from core.config import ROOT, Config, load_config

if TYPE_CHECKING:
    import geopandas as gpd

log = logging.getLogger("pipeline.context")
RAW = ROOT / "data" / "raw"
PROCESSED = ROOT / "data" / "processed"
PARCEL_CONTEXT_FIELDS = (
    "geometry_frontage_ft", "geometry_depth_ft", "geometry_dimensions_method",
    "transit_access_index", "transit_jobs_accessible",
)


def _write_parcel_context(records: list[dict]) -> None:
    """Write supplementary geometry/transit values separately from the parcel index."""
    context = {}
    for record in records:
        values = {key: record.get(key) for key in PARCEL_CONTEXT_FIELDS
                  if record.get(key) is not None}
        if values:
            context[record["id"]] = values
    PROCESSED.mkdir(parents=True, exist_ok=True)
    lines = (json.dumps({"id": parcel_id, **values}, separators=(",", ":"), sort_keys=True)
             for parcel_id, values in sorted(context.items()))
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
            if line.startswith(prefix.encode()):
                cells = line.decode().split("|")
                if len(cells) != len(header):
                    raise ValueError(f"incomplete ACS row in {url}")
                rows[cells[0][-11:]] = dict(zip(header[1:], cells[1:]))
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
                        max(0, numerator - nm) / (denominator + dm), 5)
                    value["tract_renter_cost_burden_high"] = round(
                        min(1, (numerator + nm) / max(1, denominator - dm)), 5)
        out[geoid] = value
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
    cache = RAW / "context_parcel_polygons.geojson"
    features = json.loads(cache.read_text(encoding="utf-8")).get("features", []) if cache.exists() else []
    by_id = {f["properties"]["PIN"]: f for f in features if f.get("properties", {}).get("PIN")}
    missing = [pid for pid in ids if pid not in by_id]
    if missing:
        for offset in range(0, len(missing), 100):
            batch = missing[offset:offset + 100]
            quoted = ",".join(f"'{pid}'" for pid in batch)
            result = _arcgis_geojson(spec["service_url"], {
                "f": "geojson", "where": f"PIN IN ({quoted})", "outFields": "PIN",
                "outSR": "4326", "returnGeometry": "true", "geometryPrecision": 7,
            })
            for f in result.get("features", []):
                pid = f.get("properties", {}).get("PIN")
                if pid in batch and f.get("geometry"):
                    by_id[pid] = f
            if offset % 2000 == 0:
                log.info("county parcel polygons: %d/%d requested", offset + len(batch), len(missing))
        RAW.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps({"type": "FeatureCollection", "features": list(by_id.values())},
                                    separators=(",", ":")), encoding="utf-8")
    return {pid: by_id[pid] for pid in ids if pid in by_id}


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
        response = requests.get(f"{spec['service_url']}/query", params={
            "where": where,
            "outFields": ("OBJECTID,STATEFP,COUNTYFP,TRACTCE,BLKGRPCE,"
                          f"{spec['jobs_field']},{spec['index_field']}"),
            "returnGeometry": "false", "resultRecordCount": 1000,
            "resultOffset": offset, "orderByFields": "OBJECTID", "f": "json",
        }, timeout=90)
        response.raise_for_status()
        payload = response.json()
        if "error" in payload:
            raise ValueError(f"EPA SLD query failed: {payload['error']}")
        features = payload.get("features", [])
        for feature in features:
            attrs = feature.get("attributes", {})
            try:
                geoid = (f"{int(attrs['STATEFP']):02d}{int(attrs['COUNTYFP']):03d}"
                         f"{int(attrs['TRACTCE']):06d}{int(attrs['BLKGRPCE']):1d}")
                jobs = float(attrs[spec["jobs_field"]])
                index = float(attrs[spec["index_field"]])
            except (KeyError, TypeError, ValueError):
                continue
            if len(geoid) == 12 and jobs >= 0 and 0 <= index <= 1:
                rows.append({"block_group_geoid": geoid, "jobs_accessible": jobs,
                             "transit_access_index": index})
        if len(features) < 1000:
            break
        offset += len(features)
    if not rows:
        raise ValueError("EPA SLD query returned no valid Allegheny County block groups")
    RAW.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps({"source": spec["source"], "vintage": "SLD 3.0 (2021)",
                                 "rows": rows}, separators=(",", ":")), encoding="utf-8")
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
        lengths = [((coords[i + 1][0] - coords[i][0]) ** 2 +
                    (coords[i + 1][1] - coords[i][1]) ** 2) ** 0.5
                   for i in range(4)]
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
        lons = [r["lon"] for r in records]
        lats = [r["lat"] for r in records]
        envelope = f"{min(lons)-0.01},{min(lats)-0.01},{max(lons)+0.01},{max(lats)+0.01}"
        spatial = {"geometry": envelope, "geometryType": "esriGeometryEnvelope",
                   "inSR": "4326", "spatialRel": "esriSpatialRelIntersects"}
        ids = _arcgis_geojson(spec["service_url"], {
            "f": "json", "where": "1=1", **spatial, "returnIdsOnly": "true",
        }).get("objectIds") or []
        if not ids:
            raise ValueError("FEMA query returned no Pittsburgh polygons")
        features: list[dict] = []
        # PASDA's service returns HTTP 500 for some 100-feature geometry pages.
        # Small pages keep individual complex flood polygons below its limit.
        for offset in range(0, len(ids), 25):
            result = _arcgis_geojson(spec["service_url"], {
                "f": "geojson", "objectIds": ",".join(map(str, ids[offset:offset + 25])),
                "outFields": "OBJECTID,FLD_ZONE,SFHA_TF,ZONE_SUBTY,SOURCE_CIT,VERSION_ID",
                "outSR": "4326", "returnGeometry": "true", "geometryPrecision": 7,
            })
            features.extend(result.get("features", []))
            if offset % 500 == 0:
                log.info("FEMA polygons: %d/%d requested", min(offset + 25, len(ids)), len(ids))
        if len(features) != len(ids):
            raise ValueError(f"FEMA returned {len(features)} of {len(ids)} polygons")
        RAW.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps({"type": "FeatureCollection", "features": features},
                                    separators=(",", ":")), encoding="utf-8")
    layer = gpd.read_file(cache).to_crs(4326)
    log.info("FEMA cache loaded: %d polygons", len(layer))
    return layer[layer.geometry.notna()].copy()


def _polygon_matches(records: list[dict], parcel_features: dict[str, dict],
                     layer: gpd.GeoDataFrame, value_col: str) -> dict[str, list[dict]]:
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
        else:
            point = Point(r["lon"], r["lat"])
            method = "published parcel centroid (boundary unavailable)"
        rows.append({"id": r["id"], "geometry": point, "join_method": method})
    points = gpd.GeoDataFrame(rows, geometry="geometry", crs=4326)
    target = layer.to_crs(4326).copy()
    log.info("%s: spatial join of %d parcel points to %d polygons", value_col, len(points), len(target))
    matches: dict[str, list[dict]] = {}
    if not points.empty and not target.empty:
        hits = gpd.sjoin(points, target[[value_col, "geometry"]],
                         how="inner", predicate="within")
        log.info("%s: %d point-in-polygon matches", value_col, len(hits))
        for row in hits.itertuples():
            matches.setdefault(row.id, []).append({
                "value": getattr(row, value_col), "layer_index": row.index_right,
                "join_method": row.join_method,
            })
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
        details["acs"] = {"source": acs["source"], "status": "loaded",
                          "join": "11-digit tract GEOID; 2024 ACS geography"}
    except (requests.RequestException, OSError, ValueError) as exc:
        details["acs"] = {"source": acs["source"], "status": "unavailable", "reason": str(exc)}
        log.warning("ACS context unavailable: %s", exc)
    counts["acs_income_values"] = sum(r.get("tract_median_household_income") is not None for r in records)
    counts["acs_renter_burden_values"] = sum(
        r.get("tract_renter_cost_burden_share") is not None for r in records)

    try:
        boundaries = _parcel_polygons(specs["parcel_boundaries"], [r["id"] for r in records])
    except (requests.RequestException, OSError, ValueError) as exc:
        boundaries = {}
        details["parcel_boundaries"] = {"status": "unavailable", "reason": str(exc)}
        log.warning("parcel polygons unavailable: %s", exc)
    counts["parcel_polygons_matched"] = len(boundaries)
    counts["geometry_dimensions_estimated"] = _geometry_dimensions(records, boundaries)
    transit = specs["transit_jobs"]
    try:
        _transit_access(transit, records)
        details["transit_jobs"] = {
            "source": transit["source"], "status": "loaded",
            "vintage": "EPA Smart Location Database 3.0 (2021); 2020 GTFS and travel times; 2017 LEHD",
            "join": "2020 block-group GEOID20 reconstructed from state, county, tract and group fields",
            "measure": "D5DRI relative transit jobs accessibility index and D5BR distance-decay-weighted jobs",
        }
    except (requests.RequestException, OSError, ValueError, KeyError) as exc:
        details["transit_jobs"] = {"source": transit["source"], "status": "unavailable",
                                   "reason": str(exc)}
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
                r["fema_sfha"] = any(str(fema.loc[h["layer_index"], "SFHA_TF"]).upper() == "T"
                                      for h in found)
                r["fema_join_method"] = found[0]["join_method"]
            else:
                r["fema_flood_zones"] = None
                r["fema_sfha"] = None
                r["fema_join_method"] = None
        details["flood"] = {"source": flood["source"], "status": "loaded",
                            "polygons": len(fema), "join": "parcel interior point; centroid fallback"}
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
            r["combined_sewershed_ids"] = sorted({str(h["value"]) for h in found if h["value"]}) or None
            r["sewershed_join_method"] = found[0]["join_method"] if found else None
        details["combined_sewersheds"] = {"source": sewershed["source"], "status": "loaded",
                                           "polygons": len(layer),
                                           "join": "parcel interior point; centroid fallback"}
    except (requests.RequestException, OSError, ValueError) as exc:
        details["combined_sewersheds"] = {"source": sewershed["source"], "status": "unavailable",
                                           "reason": str(exc)}
        log.warning("combined sewersheds unavailable: %s", exc)
        for r in records:
            r["combined_sewershed_ids"] = r["sewershed_join_method"] = None
    counts["combined_sewershed_matched"] = sum(r["combined_sewershed_ids"] is not None for r in records)
    details["generated_at_utc"] = datetime.now(UTC).isoformat()
    details["join_methods"] = dict(Counter(r["fema_join_method"] or "unmatched" for r in records))


def main() -> None:
    cfg = load_config()
    index_path = PROCESSED / "parcels.json"
    payload = json.loads(index_path.read_text(encoding="utf-8"))
    report_path = PROCESSED / "pipeline_report.json"
    report = json.loads(report_path.read_text(encoding="utf-8")) if report_path.exists() else {"counts": {}}
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
