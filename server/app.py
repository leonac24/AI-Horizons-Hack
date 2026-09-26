"""FastAPI app. Local: `uv run uvicorn server.app:app --reload`. Vercel: api/index.py."""

from __future__ import annotations

import json
from collections import Counter
from functools import lru_cache

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel

from core.config import ROOT, get_config
from core.engine import Analysis, analyze, work_backwards
from core.zoning import load_rules
from server.explain import explain
from server.llm import get_provider

app = FastAPI(title="Lotline API")
PARCELS_FILE = ROOT / "data" / "processed" / "parcels.json"


@lru_cache(maxsize=1)
def _index() -> dict:
    if not PARCELS_FILE.exists():
        return {"parcels": {}, "suggested": []}
    return json.loads(PARCELS_FILE.read_text())


def _parcel(parcel_id: str) -> dict:
    p = _index()["parcels"].get(parcel_id)
    if p is None:
        raise HTTPException(404, f"no vacant parcel {parcel_id!r} in the index")
    return p


@lru_cache(maxsize=512)
def _analysis(parcel_id: str, config_hash: str) -> Analysis:
    return analyze(get_config(), _parcel(parcel_id))


@app.get("/api/health")
def health() -> dict:
    cfg = get_config()
    return {"ok": True, "config_hash": cfg.hash, "parcels": len(_index()["parcels"]),
            "llm": get_provider().name}


@app.get("/api/config")
def config() -> dict:
    return get_config().public_json()


def _summary(p: dict) -> dict:
    keys = ("id", "address", "neighborhood", "zoning", "lot_area_sf", "public", "lon", "lat")
    return {k: p.get(k) for k in keys}


@app.get("/api/parcels/suggested")
def suggested() -> list[dict]:
    idx = _index()
    return [_summary(idx["parcels"][i]) for i in idx["suggested"] if i in idx["parcels"]]


@app.get("/api/parcels/search")
def search(q: str = Query(min_length=2), limit: int = 20) -> list[dict]:
    ql = q.strip().upper().replace("-", "")
    out = []
    for p in _index()["parcels"].values():
        if p["id"].startswith(ql) or ql in (p.get("address") or "").upper():
            out.append(_summary(p))
            if len(out) >= limit:
                break
    return out


@app.get("/api/parcels/{parcel_id}")
def parcel(parcel_id: str) -> dict:
    return _parcel(parcel_id)


@app.get("/api/analysis/{parcel_id}")
def analysis(parcel_id: str) -> Analysis:
    return _analysis(parcel_id, get_config().hash)


class ExplainRequest(BaseModel):
    parcel_id: str
    weights: dict[str, float]
    ranking: list[str]


@app.post("/api/explain")
def explain_route(req: ExplainRequest) -> dict:
    cfg = get_config()
    a = _analysis(req.parcel_id, cfg.hash)  # recomputed server-side; client numbers are never trusted
    known = {t.id for t in cfg.typologies}
    ranking = [t for t in req.ranking if t in known]
    return explain(cfg, get_provider(), a, req.weights, ranking)


@app.get("/api/work-backwards/{parcel_id}")
def work_backwards_route(parcel_id: str, typology: str, units: int = Query(ge=1),
                         target_ami_pct: float = Query(gt=0, le=200)) -> dict:
    try:
        return work_backwards(get_config(), _parcel(parcel_id), typology, units, target_ami_pct)
    except KeyError as e:
        raise HTTPException(400, str(e)) from e


@app.get("/api/unknowns")
def unknowns() -> dict:
    """Everything the tool does not know yet — feeds the 'What we don't know' page."""
    cfg = get_config()
    rules = load_rules(cfg)
    parcels = _index()["parcels"].values()
    by_district = Counter(p.get("zoning") or "(no district)" for p in parcels)
    reviewed = {d for d, r in rules.items()
                if any(u.get("reviewed") for u in (r.get("uses") or {}).values())}
    total = sum(by_district.values()) or 1
    covered = sum(n for d, n in by_district.items() if d in reviewed)
    report_path = ROOT / "data" / "processed" / "pipeline_report.json"
    return {
        "placeholder_assumptions": [
            {"id": k, "unit": a.unit, "rationale": a.rationale, "source": a.source}
            for k, a in cfg.assumptions.items() if a.provenance == "placeholder"],
        "unverified_sources": [
            {"id": k, "name": s.name, "note": s.note} for k, s in cfg.sources.sources.items() if s.verified is False],
        "unreviewed_districts": [
            {"district": d, "vacant_parcels": n} for d, n in by_district.most_common() if d not in reviewed],
        "vacant_parcels": total,
        "share_covered_by_reviewed_rules": round(covered / total, 4),
        "pipeline": json.loads(report_path.read_text()) if report_path.exists() else None,
    }
