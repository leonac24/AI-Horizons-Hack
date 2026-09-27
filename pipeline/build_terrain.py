"""Bake the 3D city's terrain from elevation tiles into a static heightmap.

    uv sync --group pipeline
    uv run python -m pipeline.build_terrain

Writes web/public/data/terrain.json (grid layout + provenance) and terrain.bin
(Int16 heights ×100, coarse grid then fine grid). The browser never calls the
tile server. Terrain shapes the stylized city only; no metric reads it.
"""

from __future__ import annotations

import io
import json
import logging
import math

import numpy as np
import requests
from PIL import Image

from core.config import ROOT, Config, load_config

log = logging.getLogger("pipeline")
TILE_URL = "https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png"
OUT = ROOT / "web" / "public" / "data"
RAW = ROOT / "data" / "raw" / "terrain"
WATER = -32768
SCALE = 100


def _tile_xy(lon: float, lat: float, z: int) -> tuple[float, float]:
    n = 2**z
    r = math.radians(lat)
    return (lon + 180) / 360 * n, (1 - math.log(math.tan(r) + 1 / math.cos(r)) / math.pi) / 2 * n


def _tile_xy_vec(lon: np.ndarray, lat: np.ndarray, z: int) -> tuple[np.ndarray, np.ndarray]:
    n = 2**z
    r = np.radians(lat)
    return (lon + 180) / 360 * n, (1 - np.log(np.tan(r) + 1 / np.cos(r)) / np.pi) / 2 * n


class Mosaic:
    """Decoded Terrarium tiles covering a lon/lat box at one zoom, sampled bilinearly."""

    def __init__(self, z: int, lon0: float, lat0: float, lon1: float, lat1: float):
        self.z, self.box = z, (lon0, lat0, lon1, lat1)
        x0, y1f = _tile_xy(lon0, lat0, z)
        x1f, y0 = _tile_xy(lon1, lat1, z)
        self.x0, self.y0 = int(x0), int(y0)
        nx, ny = int(x1f) - self.x0 + 1, int(y1f) - self.y0 + 1
        self.elev = np.zeros((ny * 256, nx * 256), dtype=np.float32)
        for i in range(nx):
            for j in range(ny):
                self.elev[j * 256:(j + 1) * 256, i * 256:(i + 1) * 256] = self._tile(self.x0 + i, self.y0 + j)

    def _tile(self, x: int, y: int) -> np.ndarray:
        cache = RAW / f"{self.z}_{x}_{y}.png"
        if not cache.exists():
            r = requests.get(TILE_URL.format(z=self.z, x=x, y=y), timeout=60)
            r.raise_for_status()
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_bytes(r.content)
        px = np.asarray(Image.open(io.BytesIO(cache.read_bytes())).convert("RGB"), dtype=np.float32)
        return px[..., 0] * 256 + px[..., 1] + px[..., 2] / 256 - 32768

    def covers(self, lon: np.ndarray, lat: np.ndarray) -> np.ndarray:
        lon0, lat0, lon1, lat1 = self.box
        return (lon > lon0) & (lon < lon1) & (lat > lat0) & (lat < lat1)

    def sample(self, lon: np.ndarray, lat: np.ndarray) -> np.ndarray:
        tx, ty = _tile_xy_vec(lon, lat, self.z)
        H, W = self.elev.shape
        px = np.clip((tx - self.x0) * 256 - 0.5, 0, W - 1.001)
        py = np.clip((ty - self.y0) * 256 - 0.5, 0, H - 1.001)
        i, j = px.astype(int), py.astype(int)
        u, v = px - i, py - j
        E = self.elev
        return (E[j, i] * (1 - u) + E[j, i + 1] * u) * (1 - v) + (E[j + 1, i] * (1 - u) + E[j + 1, i + 1] * u) * v


def build(cfg: Config) -> dict:
    scene = cfg.city.model_dump()["scene"]
    t = scene["terrain"]
    lon0, lat0 = scene["origin"]
    kx, kz = scene["scale"]
    mosaics = [Mosaic(t[k]["zoom"], lon0 - t[k]["half_lon"], lat0 - t[k]["half_lat"],
                      lon0 + t[k]["half_lon"], lat0 + t[k]["half_lat"]) for k in ("inner", "outer")]
    inner, outer = mosaics

    def grid(extent: float, step: float) -> tuple[np.ndarray, int]:
        n = round(extent * 2 / step)
        xs = -extent + np.arange(n + 1) * step
        X, Z = np.meshgrid(xs, xs)  # rows = z, cols = x
        lon, lat = lon0 + X / kx, lat0 - Z / kz
        e = np.where(inner.covers(lon, lat), inner.sample(lon, lat), outer.sample(lon, lat))
        r = e - t["river_pool_m"]
        h = (r / t["m_per_unit"]) * t["vertical_exaggeration"] * (1 + r / t["steepen_m"]) / t["damping"]
        q = np.round(h * SCALE).clip(-32000, 32000).astype(np.int16)
        q[e < t["river_pool_m"] + t["water_margin_m"]] = WATER
        return q, n

    coarse, cn = grid(t["coarse"]["extent"], t["coarse"]["step"])
    fine_extent = scene["half_extent"] + t["fine"]["margin"]
    fine, fn = grid(fine_extent, t["fine"]["step"])
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "terrain.bin").write_bytes(coarse.tobytes() + fine.tobytes())
    meta = {
        "config_hash": cfg.hash,
        "source": t["source"],
        "scale": SCALE,
        "water": WATER,
        "coarse": {"extent": t["coarse"]["extent"], "step": t["coarse"]["step"], "n": cn},
        "fine": {"extent": fine_extent, "step": t["fine"]["step"], "n": fn},
    }
    (OUT / "terrain.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
    log.info("terrain: coarse %d², fine %d², water share %.1f%%", cn + 1, fn + 1,
             100 * float((fine == WATER).mean()))
    return meta


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    build(load_config())
