"""Bake the 3D city's orientation layers: neighborhood labels, streets, lot outlines.

    uv sync --group pipeline
    uv run python -m pipeline.build_basemap

Writes web/public/data/basemap/{neighborhoods,streets,lots}.json. Coordinates are
integers: (lon - origin_lon) * q and (lat - origin_lat) * q, with `origin` and `q`
in each file. The browser never calls these services. The layers help people
find their block; no metric reads them. A source that fails to load writes no
file, and the 3D city draws without that layer.
"""

from __future__ import annotations

import json
import logging

import geopandas as gpd
import requests
from shapely.geometry import LineString, MultiLineString, MultiPolygon, Polygon, shape
from shapely.ops import linemerge, polylabel

from core.config import ROOT, Config, load_config
from pipeline.adapters.ckan import CkanDownload
from pipeline.enrich_context import _parcel_polygons

log = logging.getLogger("pipeline")
OUT = ROOT / "web" / "public" / "data" / "basemap"
PROCESSED = ROOT / "data" / "processed"
Q_STREETS = 100_000  # ~1 m
Q_LOTS = 1_000_000  # ~0.1 m


def _quantize(coords, origin: tuple[float, float], q: int) -> list[int]:
    lon0, lat0 = origin
    out: list[int] = []
    for lon, lat, *_ in coords:
        out += [round((lon - lon0) * q), round((lat - lat0) * q)]
    return out


def _write(name: str, payload: dict) -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"{name}.json"
    path.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
    return path.stat().st_size


def _neighborhoods(cfg: Config, origin: tuple[float, float]) -> dict | None:
    spec = cfg.city.model_dump()["neighborhoods"]
    fetched = CkanDownload(spec["source"]).fetch(cfg)
    if not fetched.ok:
        return None
    hoods = gpd.read_file(fetched.data)[[spec["name_field"], "geometry"]].to_crs(4326)
    metric = hoods.to_crs(hoods.estimate_utm_crs())
    labels = []
    for name, geom in zip(hoods[spec["name_field"]], metric.geometry):
        if not name or geom is None or geom.is_empty:
            continue
        # Label inside the largest part, at the point farthest from its edges.
        part = max(geom.geoms, key=lambda g: g.area) if isinstance(geom, MultiPolygon) else geom
        pt = gpd.GeoSeries([polylabel(part, tolerance=10)], crs=metric.crs).to_crs(4326).iloc[0]
        labels.append([str(name), *_quantize([(pt.x, pt.y)], origin, Q_STREETS), round(geom.area / 1e6, 3)])
    labels.sort(key=lambda r: -r[3])
    return {"source": spec["source"], "origin": origin, "q": Q_STREETS,
            "fields": ["name", "x", "y", "area_km2"], "labels": labels}


def _streets(cfg: Config, origin: tuple[float, float]) -> dict | None:
    spec = cfg.city.model_dump()["scene"]["basemap"]["streets"]
    fetched = CkanDownload(spec["source"]).fetch(cfg)
    if not fetched.ok:
        return None
    tier_of = {c: i for i, t in enumerate(spec["tiers"]) for c in t["classes"]}
    cols = [spec["class_field"], *spec["drop_if_set"], "geometry"]
    gdf = gpd.read_file(fetched.data, columns=cols).to_crs(4326)
    for col in spec["drop_if_set"]:
        gdf = gdf[gdf[col].isna() | (gdf[col].astype(str).str.strip() == "")]
    gdf = gdf[gdf[spec["class_field"]].isin(tier_of)]
    metric_crs = gdf.estimate_utm_crs()
    lines: list[list[int]] = []
    for cls, group in gdf.groupby(spec["class_field"]):
        merged = linemerge(list(group.to_crs(metric_crs).geometry.explode(index_parts=False)))
        simple = gpd.GeoSeries([merged], crs=metric_crs).simplify(spec["simplify_m"]).to_crs(4326).iloc[0]
        parts = simple.geoms if isinstance(simple, MultiLineString) else [simple]
        for part in parts:
            if isinstance(part, LineString) and len(part.coords) > 1:
                lines.append([tier_of[cls], *_quantize(part.coords, origin, Q_STREETS)])
    lines.sort(key=lambda r: r[0])
    return {"source": spec["source"], "origin": origin, "q": Q_STREETS,
            "tiers": [t["id"] for t in spec["tiers"]], "lines": lines}


def _lots(cfg: Config, origin: tuple[float, float]) -> dict | None:
    city = cfg.city.model_dump()
    spec = city["context"]["parcel_boundaries"]
    ids = list(json.loads((PROCESSED / "parcels.json").read_text(encoding="utf-8"))["parcels"])
    try:
        features = _parcel_polygons(spec, ids)
    except (requests.RequestException, OSError, ValueError) as exc:
        log.warning("lot outlines unavailable: %s", exc)
        return None
    if not features:
        return None
    rows = [(pid, shape(f["geometry"])) for pid, f in features.items()]
    geo = gpd.GeoSeries([g for _, g in rows], crs=4326)
    metric_crs = geo.estimate_utm_crs()
    simple = geo.to_crs(metric_crs).simplify(city["scene"]["basemap"]["lots"]["simplify_m"]).to_crs(4326)
    lots = []
    for (pid, _), geom in zip(rows, simple):
        polys = geom.geoms if isinstance(geom, MultiPolygon) else [geom]
        rings = [_quantize(p.exterior.coords, origin, Q_LOTS) for p in polys
                 if isinstance(p, Polygon) and not p.is_empty]
        if rings:
            lots.append([pid, *rings])
    return {"source": spec["source"], "origin": origin, "q": Q_LOTS, "matched": len(lots),
            "requested": len(ids), "lots": lots}


def build(cfg: Config) -> dict:
    origin = tuple(cfg.city.model_dump()["scene"]["origin"])
    report = {}
    for name, fn in (("neighborhoods", _neighborhoods), ("streets", _streets), ("lots", _lots)):
        payload = fn(cfg, origin)
        if payload is None:
            report[name] = "unavailable"
            log.warning("%s: source unavailable, no file written", name)
            continue
        payload["config_hash"] = cfg.hash
        size = _write(name, payload)
        report[name] = size
        log.info("%s: %.0f KB", name, size / 1024)
    return report


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    build(load_config())
