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
import re
from collections import Counter

import geopandas as gpd
import pandas as pd

from core.config import ROOT, Config, load_config
from pipeline.adapters.ckan import CkanDatastore, CkanDownload
from pipeline.steps.suggest import pick_suggested

log = logging.getLogger("pipeline")
PROCESSED = ROOT / "data" / "processed"
WEB_DATA = ROOT / "web" / "public" / "data"


def build(cfg: Config) -> dict:
    city = cfg.city.model_dump()
    pc = city["parcels"]
    report: dict = {"config_hash": cfg.hash, "sources": {}, "counts": {}}

    def note(result):
        report["sources"][result.source_id] = {"provenance": result.provenance, "notes": result.notes}
        return result

    # 1. Vacant parcels from assessments (no owner names / owner addresses fetched).
    keep = pc["keep_fields"]
    fields = sorted({*keep, pc["municipality_field"], pc["vacant_use_field"]})
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
    df = df[list(keep)].rename(columns=keep)
    df = df.drop_duplicates("id")
    report["counts"]["vacant_in_city"] = len(df)

    # 2. Location + census geography from parcel centroids.
    cf = pc["centroid_fields"]
    cent = note(CkanDatastore(pc["centroids_source"], list(cf), pc["centroids_filter"]).fetch(cfg))
    cdf = pd.DataFrame(cent.data).rename(columns=cf) if cent.ok else pd.DataFrame(columns=list(cf.values()))
    df = df.merge(cdf.drop_duplicates("id"), on="id", how="left")
    df["tract"] = df["tract"].map(lambda t: f"{city['state_fips']}{city['county_fips']}{t}" if pd.notna(t) else None)
    missing_loc = df["lon"].isna().sum()
    report["counts"]["missing_location"] = int(missing_loc)
    df = df[df["lon"].notna()].copy()

    # 3. Public ownership flag.
    pl = city["public_land"]
    pub = note(CkanDatastore(pl["source"], [pl["id_field"], *pl["keep_fields"]]).fetch(cfg))
    pdf = pd.DataFrame(pub.data).rename(columns={pl["id_field"]: "id", **pl["keep_fields"]})
    df = df.merge(pdf.drop_duplicates("id"), on="id", how="left") if pub.ok else df
    df["public"] = df.get("public_inventory_type", pd.Series(index=df.index)).notna()

    gdf = gpd.GeoDataFrame(df, geometry=gpd.points_from_xy(df["lon"], df["lat"]), crs="EPSG:4326")

    # 4. Zoning district (point-in-polygon at the centroid).
    zl = city["zoning_layer"]
    z = note(CkanDownload(zl["source"]).fetch(cfg))
    if z.ok:
        zg = gpd.read_file(z.data)[[zl["district_field"], zl["label_field"], zl["code_link_field"], "geometry"]]
        zg = zg.rename(columns={zl["district_field"]: "zoning", zl["label_field"]: "zoning_label",
                                zl["code_link_field"]: "zoning_code_url"}).to_crs(4326)
        gdf = gpd.sjoin(gdf, zg, how="left", predicate="within").drop(columns="index_right")
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
        hit = gpd.sjoin(gdf[["geometry"]], layer, how="inner", predicate="within").index.unique()
        gdf[flag] = gdf.index.isin(hit)
        report["counts"][f"flag_{flag}"] = int(gdf[flag].sum())

    gdf["lot_area_sf"] = pd.to_numeric(gdf["lot_area_sf"], errors="coerce")
    gdf["land_value_usd"] = pd.to_numeric(gdf["land_value_usd"], errors="coerce")
    gdf["address"] = (
        gdf["house_number"].fillna("").astype(str).str.replace(r"\.0$", "", regex=True).replace("0", "")
        + " " + gdf["street"].fillna("")
    ).str.strip()

    cols = ["id", "address", "zip", "lon", "lat", "lot_area_sf", "land_value_usd", "land_use", "owner_type",
            "public", "public_inventory_type", "public_status", "zoning", "zoning_label", "zoning_code_url",
            "neighborhood", "tract", "block_group", *city["hazards"].keys()]
    out = pd.DataFrame(gdf[[c for c in cols if c in gdf.columns]])
    out = out.astype(object).where(out.notna(), None)
    records = out.to_dict(orient="records")
    for r in records:
        r["lon"], r["lat"] = round(r["lon"], 6), round(r["lat"], 6)
        if r.get("zip") is not None:
            r["zip"] = str(int(float(r["zip"])))
        if r.get("block_group") is not None:
            r["block_group"] = str(int(r["block_group"]))

    report["counts"]["indexed"] = len(records)
    suggested = pick_suggested(records, city["suggested_lots"])
    report["counts"]["suggested"] = len(suggested)

    PROCESSED.mkdir(parents=True, exist_ok=True)
    WEB_DATA.mkdir(parents=True, exist_ok=True)
    (PROCESSED / "parcels.json").write_text(
        json.dumps({"config_hash": cfg.hash, "suggested": suggested, "parcels": {r["id"]: r for r in records}})
    )
    (WEB_DATA / "parcels.geojson").write_text(json.dumps(_points(records, city["hazards"].keys()), separators=(",", ":")))

    by_district = Counter(r["zoning"] or "(none)" for r in records)
    rules_path = ROOT / cfg.zoning.priority_file
    rules_path.write_text(json.dumps([{"district": d, "vacant_parcels": n} for d, n in by_district.most_common()], indent=1))
    (PROCESSED / "pipeline_report.json").write_text(json.dumps(report, indent=2))
    log.info("indexed %d vacant parcels; report: %s", len(records), json.dumps(report["counts"]))
    return report


def _points(records: list[dict], hazard_keys) -> dict:
    """Minimal properties so the map file stays small."""
    feats = []
    for r in records:
        props = {"id": r["id"], "a": r["lot_area_sf"], "z": r["zoning"], "n": r["neighborhood"],
                 "p": 1 if r["public"] else 0, "ad": r["address"]}
        for k in hazard_keys:
            props[k] = 1 if r.get(k) else 0
        feats.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [r["lon"], r["lat"]]},
                      "properties": props})
    return {"type": "FeatureCollection", "features": feats}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    build(load_config())
