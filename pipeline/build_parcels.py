"""Build the citywide vacant-parcel index.

    uv run python -m pipeline.build_parcels

Outputs
  data/processed/parcels.json          full index the server reads (keyed by parcel id)
  web/public/data/parcels.geojson      compact points the map reads
  data/processed/pipeline_report.json  counts + which sources were placeholders
  pipeline/zoning/review_priority.json districts ordered by vacant-parcel count
"""

from __future__ import annotations

import json
import logging
import math
import re
from collections import Counter

import geopandas as gpd
import pandas as pd

from core.config import ROOT, Config, load_config
from core.engine import lot_shape, pure_buildings
from pipeline.adapters.ckan import CkanDatastore, CkanDownload
from pipeline.enrich_context import (
    _address_point_locations,
    _parcel_polygons,
    _strip_parcel_context,
    _write_parcel_context,
    enrich_records,
)
from pipeline.steps.suggest import pick_suggested

log = logging.getLogger("pipeline")
PROCESSED = ROOT / "data" / "processed"
WEB_DATA = ROOT / "web" / "public" / "data"


def build(cfg: Config) -> dict:
    city = cfg.city.model_dump()
    pc = city["parcels"]
    report: dict = {"config_hash": cfg.hash, "sources": {}, "counts": {}}

    def note(result):
        report["sources"][result.source_id] = {
            "provenance": result.provenance,
            "notes": result.notes,
        }
        return result

    # 1. Vacant parcels from assessments (no owner names / owner addresses fetched).
    keep = pc["keep_fields"]
    shape = pc["lot_shape"]
    fields = sorted({*keep, pc["municipality_field"], pc["vacant_use_field"], shape["legal_field"]})
    assess = note(
        CkanDatastore(
            pc["assessments_source"], fields, {pc["vacant_use_field"]: pc["vacant_use_values"]}
        ).fetch(cfg)
    )
    if not assess.ok:
        raise SystemExit("assessments unavailable — cannot build a parcel index")
    df = pd.DataFrame(assess.data)
    muni = re.compile(pc["municipality_pattern"])
    df = df[df[pc["municipality_field"]].fillna("").str.contains(muni)]
    area_field = next(k for k, v in keep.items() if v == "lot_area_sf")
    df = df.assign(**_lot_dims(df, shape, area_field)).drop(columns=[shape["legal_field"]])
    df = df[[*keep, "frontage_ft", "depth_ft"]].rename(columns=keep)
    df = df.drop_duplicates("id")
    report["counts"]["vacant_in_city"] = len(df)
    report["counts"]["lot_dims_from_legal_description"] = int(df["frontage_ft"].notna().sum())

    # 2. Query county polygons before any location filtering. A polygon interior
    # point is the preferred map point; centroid and PIN-matched address point
    # are progressively less precise fallbacks.
    context_specs = city["context"]
    try:
        boundaries = _parcel_polygons(
            context_specs["parcel_boundaries"], df["id"].astype(str).tolist()
        )
    except (OSError, ValueError, TypeError, KeyError) as exc:
        # Keep the parcel cohort even if this optional source is down.
        boundaries = {}
        report.setdefault("context", {})["parcel_boundaries"] = {
            "status": "unavailable",
            "reason": str(exc),
        }
    report["counts"]["parcel_polygons_matched"] = len(boundaries)

    # 3. Census geographies and fallback locations from published parcel centroids.
    cf = pc["centroid_fields"]
    cent = note(CkanDatastore(pc["centroids_source"], list(cf), pc["centroids_filter"]).fetch(cfg))
    cdf = (
        pd.DataFrame(cent.data).rename(columns=cf)
        if cent.ok
        else pd.DataFrame(columns=list(cf.values()))
    )
    df = df.merge(cdf.drop_duplicates("id"), on="id", how="left")
    df["tract"] = df["tract"].map(
        lambda t: f"{city['state_fips']}{city['county_fips']}{t}" if pd.notna(t) else None
    )
    df["location_method"] = None
    for ix, row in df.iterrows():
        lon, lat, method = _choose_location(
            row.get("lon"), row.get("lat"), boundaries.get(str(row["id"]))
        )
        df.at[ix, "lon"], df.at[ix, "lat"], df.at[ix, "location_method"] = lon, lat, method
    missing_ids = df.loc[df["lon"].isna() | df["lat"].isna(), "id"].astype(str).tolist()
    if missing_ids:
        try:
            address_spec = cfg.sources.sources["allegheny_address_points"]
            address_locations = _address_point_locations(
                {"service_url": address_spec.url}, missing_ids
            )
            for ix in df.index[df["id"].astype(str).isin(address_locations)]:
                lon, lat = address_locations[str(df.at[ix, "id"])]
                df.at[ix, "lon"], df.at[ix, "lat"] = lon, lat
                df.at[ix, "location_method"] = "PIN-matched county address point (approximate)"
        except (OSError, ValueError, TypeError, KeyError) as exc:
            report.setdefault("context", {})["address_points"] = {
                "status": "unavailable",
                "reason": str(exc),
            }
    report["counts"]["missing_location"] = int((df["lon"].isna() | df["lat"].isna()).sum())
    report["counts"]["location_from_polygon"] = int(
        df["location_method"].eq("county parcel polygon interior point").sum()
    )
    report["counts"]["location_from_centroid"] = int(
        df["location_method"].eq("published parcel centroid").sum()
    )
    report["counts"]["location_from_address_point"] = int(
        df["location_method"].str.startswith("PIN-matched county address point", na=False).sum()
    )

    # 3. Public ownership flag.
    pl = city["public_land"]
    pub = note(CkanDatastore(pl["source"], [pl["id_field"], *pl["keep_fields"]]).fetch(cfg))
    pdf = pd.DataFrame(pub.data).rename(columns={pl["id_field"]: "id", **pl["keep_fields"]})
    df = df.merge(pdf.drop_duplicates("id"), on="id", how="left") if pub.ok else df
    df["public"] = df.get("public_inventory_type", pd.Series(index=df.index)).notna()

    located = (
        df["lon"].notna()
        & df["lat"].notna()
        & ~df["location_method"].fillna("").str.startswith("PIN-matched county address point")
    )
    gdf = gpd.GeoDataFrame(
        df.loc[located].copy(),
        geometry=gpd.points_from_xy(df.loc[located, "lon"], df.loc[located, "lat"]),
        crs="EPSG:4326",
    )

    # 4. Zoning district (point-in-polygon at the centroid).
    zl = city["zoning_layer"]
    z = note(CkanDownload(zl["source"]).fetch(cfg))
    if z.ok:
        zg = gpd.read_file(z.data)[
            [zl["district_field"], zl["label_field"], zl["code_link_field"], "geometry"]
        ]
        zg = zg.rename(
            columns={
                zl["district_field"]: "zoning",
                zl["label_field"]: "zoning_label",
                zl["code_link_field"]: "zoning_code_url",
            }
        ).to_crs(4326)
        if gdf.empty:
            gdf[["zoning", "zoning_label", "zoning_code_url"]] = None
        else:
            gdf = gpd.sjoin(gdf, zg, how="left", predicate="within").drop(
                columns="index_right", errors="ignore"
            )
            gdf = gdf[~gdf.index.duplicated()]
    else:
        gdf["zoning"] = None

    # 5. Hazard flags (centroid within layer).
    for flag, spec in city["hazards"].items():
        res = note(CkanDownload(spec["source"]).fetch(cfg))
        if not res.ok:
            gdf[flag] = None  # unknown, not False
            continue
        layer = gpd.read_file(res.data).to_crs(4326)[["geometry"]]
        hit = (
            gpd.sjoin(gdf[["geometry"]], layer, how="inner", predicate="within").index.unique()
            if not gdf.empty
            else []
        )
        gdf[flag] = gdf.index.isin(hit)
        report["counts"][f"flag_{flag}"] = int(gdf[flag].sum())

    # Map overlays are point-based and only run for located parcels. Reattach
    # their results to every indexed PIN so null-location records remain searchable.
    spatial_cols = [
        c
        for c in ["zoning", "zoning_label", "zoning_code_url", *city["hazards"].keys()]
        if c in gdf.columns
    ]
    overlay = pd.DataFrame(gdf[spatial_cols], index=gdf.index)
    df = df.join(overlay, how="left", rsuffix="_spatial")
    for col in spatial_cols:
        if f"{col}_spatial" in df:
            df[col] = df.pop(f"{col}_spatial")
    gdf = df
    gdf["lot_area_sf"] = pd.to_numeric(gdf["lot_area_sf"], errors="coerce")
    gdf["land_value_usd"] = pd.to_numeric(gdf["land_value_usd"], errors="coerce")
    gdf = _null_reported_assessment_zeros(gdf)
    report["counts"]["assessment_zero_lot_area"] = int(
        gdf["assessment_zero_fields"].map(lambda fields: "lot_area_sf" in fields).sum()
    )
    report["counts"]["assessment_zero_land_value"] = int(
        gdf["assessment_zero_fields"].map(lambda fields: "land_value_usd" in fields).sum()
    )
    gdf["address"] = (
        gdf["house_number"]
        .fillna("")
        .astype(str)
        .str.replace(r"\.0$", "", regex=True)
        .replace("0", "")
        + " "
        + gdf["street"].fillna("")
    ).str.strip()

    cols = [
        "id",
        "address",
        "zip",
        "lon",
        "lat",
        "location_method",
        "lot_area_sf",
        "frontage_ft",
        "depth_ft",
        "land_value_usd",
        "land_use",
        "owner_type",
        "public",
        "public_inventory_type",
        "public_status",
        "zoning",
        "zoning_label",
        "zoning_code_url",
        "neighborhood",
        "tract",
        "block_group",
        "assessment_zero_fields",
        *city["hazards"].keys(),
    ]
    out = pd.DataFrame(gdf[[c for c in cols if c in gdf.columns]])
    out = out.astype(object).where(out.notna(), None)
    records = out.to_dict(orient="records")
    for r in records:
        r["lon"] = round(r["lon"], 6) if r["lon"] is not None else None
        r["lat"] = round(r["lat"], 6) if r["lat"] is not None else None
        if r.get("zip") is not None:
            r["zip"] = str(int(float(r["zip"])))
        if r.get("block_group") is not None:
            r["block_group"] = str(int(r["block_group"]))

    # Official tract estimates and mapped site context are optional enrichments.
    # A missing supplemental source never removes an indexed lot.
    enrich_records(cfg, records, report)

    report["counts"]["indexed"] = len(records)

    def _any_form_fits(r: dict) -> bool:
        shape = lot_shape(cfg, r)
        return any(
            pure_buildings(t, shape, float(r.get("lot_area_sf") or 0))[1] for t in cfg.typologies
        )

    suggested = pick_suggested(records, city["suggested_lots"], usable=_any_form_fits)
    report["counts"]["suggested"] = len(suggested)

    PROCESSED.mkdir(parents=True, exist_ok=True)
    WEB_DATA.mkdir(parents=True, exist_ok=True)
    _write_parcel_context(records)
    _strip_parcel_context(records)
    (PROCESSED / "parcels.json").write_text(
        json.dumps(
            {
                "config_hash": cfg.hash,
                "suggested": suggested,
                "parcels": {r["id"]: r for r in records},
            }
        ),
        encoding="utf-8",
    )
    (WEB_DATA / "parcels.geojson").write_text(
        json.dumps(_points(records, city["hazards"].keys()), separators=(",", ":")),
        encoding="utf-8",
    )

    by_district = Counter(r["zoning"] or "(none)" for r in records)
    rules_path = ROOT / cfg.zoning.priority_file
    rules_path.write_text(
        json.dumps(
            [{"district": d, "vacant_parcels": n} for d, n in by_district.most_common()], indent=1
        ),
        encoding="utf-8",
    )
    (PROCESSED / "pipeline_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    log.info("indexed %d vacant parcels; report: %s", len(records), json.dumps(report["counts"]))
    return report


def _lot_dims(df: pd.DataFrame, shape: dict, area_field: str) -> dict[str, pd.Series]:
    """Frontage/depth in feet from the legal description, kept only when their
    product agrees with the assessed lot area."""
    dims = df[shape["legal_field"]].fillna("").str.extract(shape["dims_pattern"]).astype(float)
    front, depth = dims[0], dims[1]
    area = pd.to_numeric(df[area_field], errors="coerce")
    lo, hi = shape["area_tolerance"]
    ok = (front > 0) & (depth > 0) & ((front * depth / area).between(lo, hi))
    return {"frontage_ft": front.where(ok).round(1), "depth_ft": depth.where(ok).round(1)}


def _choose_location(
    lon, lat, feature: dict | None = None, address_location: tuple[float, float] | None = None
):
    """Return county-polygon interior, published centroid, address point, or null."""
    if feature and feature.get("geometry"):
        try:
            from shapely.geometry import shape

            point = shape(feature["geometry"]).representative_point()
            if not point.is_empty:
                return point.x, point.y, "county parcel polygon interior point"
        except (TypeError, ValueError):
            pass
    try:
        if pd.notna(lon) and pd.notna(lat):
            lon_value, lat_value = float(lon), float(lat)
            if (
                math.isfinite(lon_value)
                and math.isfinite(lat_value)
                and -180 <= lon_value <= 180
                and -90 <= lat_value <= 90
            ):
                return lon_value, lat_value, "published parcel centroid"
    except (TypeError, ValueError):
        pass
    if address_location is not None:
        return (
            address_location[0],
            address_location[1],
            "PIN-matched county address point (approximate)",
        )
    return None, None, None


def _null_reported_assessment_zeros(df: pd.DataFrame) -> pd.DataFrame:
    """Keep county-reported zero flags, but don't present impossible/missing values as usable."""
    result = df.copy()
    result["assessment_zero_fields"] = result.apply(
        lambda row: [
            field
            for field in ("lot_area_sf", "land_value_usd")
            if pd.notna(row[field]) and row[field] == 0
        ],
        axis=1,
    )
    for field in ("lot_area_sf", "land_value_usd"):
        result.loc[result[field] == 0, field] = None
    return result


def _points(records: list[dict], hazard_keys) -> dict:
    """Minimal properties so the map file stays small."""
    feats = []
    for r in records:
        if r.get("lon") is None or r.get("lat") is None:
            continue  # Null-coordinate PINs stay indexed/searchable, not drawn at a false point.
        if not (math.isfinite(float(r["lon"])) and math.isfinite(float(r["lat"]))):
            continue
        props = {
            "id": r["id"],
            "a": r["lot_area_sf"],
            "z": r["zoning"],
            "n": r["neighborhood"],
            "p": 1 if r["public"] else 0,
            "ad": r["address"],
        }
        for k in hazard_keys:
            props[k] = None if r.get(k) is None else int(bool(r[k]))
        props["fh"] = None if r.get("fema_sfha") is None else int(r["fema_sfha"])
        feats.append(
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [r["lon"], r["lat"]]},
                "properties": props,
            }
        )
    return {"type": "FeatureCollection", "features": feats}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    build(load_config())
