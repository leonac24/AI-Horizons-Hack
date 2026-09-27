"""FastAPI app. Local: `uv run uvicorn server.app:app --reload`. Vercel: api/index.py.

This API is public, unauthenticated and read-only. Every endpoint is safe and
idempotent; see docs/BACKEND.md for the contract, the limits and curl examples.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from collections import Counter, deque
from functools import lru_cache

from fastapi import APIRouter, FastAPI, HTTPException, Path, Query, Request, Response
from pydantic import BaseModel, Field

from core.config import ROOT, get_config
from core.engine import Analysis, analyze, work_backwards
from core.plan import Placement, PlanResult, analyze_plan
from core.zoning import load_rules
from server.explain import explain
from server.llm import get_provider

log = logging.getLogger("lotline.api")

app = FastAPI(
    title="Lotline API",
    summary="Read-only decision-support data for Pittsburgh vacant parcels.",
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
)
PARCELS_FILE = ROOT / "data" / "processed" / "parcels.json"

# Load the config once, right now, when Python first imports this file - not
# inside each route function. It has to happen here because FastAPI reads the
# limit numbers below while it is building the route definitions, which happens
# at import time.
#
# Useful side effect: if the config is broken, the app now refuses to start and
# says why, instead of starting fine and then failing on some later request.
_API = get_config().app.api
_PARCEL_ID_FORMAT = get_config().parcel_id_format

# Every route is declared on this router so the whole API can be mounted at more
# than one prefix. Hosts differ in whether they hand the function the original
# path or the rewritten one, and a 404 caused by a prefix mismatch is an
# expensive thing to debug during a deploy. See docs/BACKEND.md.
api = APIRouter()


# --- cross-cutting ---------------------------------------------------------------
@app.middleware("http")
async def security_headers(request: Request, call_next):
    """Defence in depth for a JSON API. The API never returns HTML, so the cheapest
    real win is stopping a browser from sniffing a response into something
    executable, and keeping parcel ids out of Referer headers to third parties."""
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Cross-Origin-Resource-Policy", "same-origin")
    return response


@app.exception_handler(Exception)
async def unhandled(request: Request, exc: Exception) -> Response:
    """Never let an exception string reach a client. Tracebacks leak file paths,
    config keys and library versions; the client only needs to know we failed."""
    log.exception("unhandled error on %s %s", request.method, request.url.path)
    return Response(
        content=json.dumps({"detail": "internal error"}),
        status_code=500,
        media_type="application/json",
    )


class _RateLimiter:
    """Fixed-window limiter for the one endpoint that costs money per call.

    In-process, so on a serverless host the ceiling is per warm instance rather
    than global — this is a cost guardrail, not an access control. Anything
    stronger needs shared state (see docs/BACKEND.md).
    """

    def __init__(self, per_minute: int) -> None:
        self.per_minute = per_minute
        self._hits: dict[str, deque[float]] = {}

    def check(self, key: str, now: float | None = None) -> bool:
        now = time.monotonic() if now is None else now
        q = self._hits.setdefault(key, deque())
        while q and now - q[0] > 60:
            q.popleft()
        if len(q) >= self.per_minute:
            return False
        q.append(now)
        if len(self._hits) > 4096:  # bound memory against spoofed client ips
            self._hits.clear()
        return True


@lru_cache(maxsize=1)
def _explain_limiter() -> _RateLimiter:
    return _RateLimiter(get_config().app.api.explain_requests_per_minute)


def _client_key(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for", "")
    return (fwd.split(",")[0].strip() or (request.client.host if request.client else "unknown"))[:64]


def _etag(payload: object) -> str:
    return '"' + hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()[:32] + '"'


def _conditional(request: Request, response: Response, payload: object) -> bool:
    """Set validators and report whether the client's copy is already current.

    Analyses are pure functions of (parcel, config), so they are safely cacheable
    and a repeat request should cost nothing.
    """
    tag = _etag(payload)
    response.headers["ETag"] = tag
    response.headers["Cache-Control"] = f"public, max-age={_API.cache_max_age_seconds}"
    return request.headers.get("if-none-match") == tag


# --- data ------------------------------------------------------------------------
@lru_cache(maxsize=1)
def _index() -> dict:
    if not PARCELS_FILE.exists():
        log.warning("no parcel index at %s — serving an empty index", PARCELS_FILE)
        return {"parcels": {}, "suggested": []}
    return json.loads(PARCELS_FILE.read_text(encoding="utf-8"))


def _parcel(parcel_id: str) -> dict:
    p = _index()["parcels"].get(parcel_id)
    if p is None:
        raise HTTPException(404, "no vacant parcel with that id in the index")
    return p


@lru_cache(maxsize=_API.analysis_cache_entries)
def _analysis_cached(parcel_id: str, config_hash: str) -> Analysis:
    return analyze(get_config(), _parcel(parcel_id))


def _analysis(parcel_id: str) -> Analysis:
    return _analysis_cached(parcel_id, get_config().hash)


# What a parcel id in a URL is allowed to look like. The rules come from
# city.yaml, because "ids are capital letters and digits" is a fact about
# Pittsburgh parcels, not a setting anyone would tune.
#
# FastAPI applies these checks before our code runs, so a bad id comes back as
# a 422 error and never reaches a lookup. It also means an id can never contain
# a slash or a dot, so a URL can't be used to reach a file on the server.
_PID = {"min_length": _PARCEL_ID_FORMAT.min_chars, "max_length": _PARCEL_ID_FORMAT.max_chars,
        "pattern": _PARCEL_ID_FORMAT.pattern}
PARCEL_ID = Path(**_PID)
ParcelId = Field(**_PID)


# --- routes ----------------------------------------------------------------------
@api.get("/health", summary="Liveness plus what this instance loaded")
def health() -> dict:
    cfg = get_config()
    provider = get_provider()
    return {"ok": True, "config_hash": cfg.hash, "parcels": len(_index()["parcels"]),
            "llm": provider.name, "llm_note": getattr(provider, "reason", None)}


@api.get("/config", summary="Labels, criteria, typologies and assumptions for the UI")
def config(request: Request, response: Response) -> dict:
    payload = get_config().public_json()
    if _conditional(request, response, payload):
        return Response(status_code=304)  # type: ignore[return-value]
    return payload


def _summary(p: dict) -> dict:
    keys = ("id", "address", "neighborhood", "zoning", "lot_area_sf", "public", "lon", "lat")
    return {k: p.get(k) for k in keys}


@api.get("/parcels/suggested", summary="A geographically varied starting sample")
def suggested() -> list[dict]:
    idx = _index()
    return [_summary(idx["parcels"][i]) for i in idx["suggested"] if i in idx["parcels"]]


@api.get("/parcels/search", summary="Prefix search on parcel id, substring on address")
def search(q: str = Query(min_length=_API.search_query_min_chars, max_length=_API.search_query_max_chars),
           limit: int = Query(20, ge=1, le=_API.search_limit_max)) -> list[dict]:
    # Both limits above come from config, and that is the only place they are
    # checked. There used to be a second check down here against the same config
    # values. That looks safer, but it wasn't: the numbers up in the function
    # signature were a separate hand-typed copy. So raising the limit in the
    # YAML file did nothing at all - the signature still rejected at the old
    # number, before this code ever ran.
    ql = q.strip().upper().replace("-", "")
    out: list[dict] = []
    for p in _index()["parcels"].values():
        if p["id"].startswith(ql) or ql in (p.get("address") or "").upper():
            out.append(_summary(p))
            if len(out) >= limit:
                break
    return out


@api.get("/parcels/{parcel_id}", summary="One parcel's index record")
def parcel(parcel_id: str = PARCEL_ID) -> dict:
    return _parcel(parcel_id)


@api.get("/analysis/{parcel_id}", summary="Every typology scored on one parcel, with provenance")
def analysis(request: Request, response: Response, parcel_id: str = PARCEL_ID) -> Analysis:
    result = _analysis(parcel_id)
    if _conditional(request, response, result.model_dump(mode="json")):
        return Response(status_code=304)  # type: ignore[return-value]
    return result


class PlanRequest(BaseModel):
    """Buildings placed in the 3D lot view, as counts per building type. Where
    they sit on the lot is the client's concern; the evidence only needs counts."""

    placements: list[Placement] = Field(default_factory=list)


@api.post("/analysis/{parcel_id}/plan", summary="Evaluate a mixed plan of buildings on one parcel")
def plan_route(req: PlanRequest, parcel_id: str = PARCEL_ID) -> PlanResult:
    cfg = get_config()
    if (len(req.placements) > cfg.app.api.plan_max_buildings
            or sum(p.count for p in req.placements) > cfg.app.api.plan_max_buildings):
        raise HTTPException(413, "too many buildings in this plan")
    if any(p.count < 0 for p in req.placements):
        raise HTTPException(422, "building counts cannot be negative")
    known = {t.id for t in cfg.typologies}
    if any(p.typology_id not in known for p in req.placements):
        raise HTTPException(400, "unknown typology")
    try:
        return analyze_plan(cfg, _parcel(parcel_id), req.placements)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e


class ExplainRequest(BaseModel):
    """Weights and ranking are the caller's *values*. They are echoed into the
    prompt but never trusted as evidence: the server recomputes every number.
    """

    parcel_id: str = ParcelId
    weights: dict[str, float] = Field(default_factory=dict)
    ranking: list[str] = Field(default_factory=list)


@api.post("/explain", summary="Grounded prose over already-computed metrics")
def explain_route(req: ExplainRequest, request: Request) -> dict:
    cfg = get_config()
    limits = cfg.app.api
    if len(req.weights) > limits.explain_max_weights or len(req.ranking) > limits.explain_max_ranking:
        raise HTTPException(413, "too many weights or ranking entries")
    if not _explain_limiter().check(_client_key(request)):
        raise HTTPException(429, "too many explanation requests; try again shortly")

    a = _analysis(req.parcel_id)  # recomputed server-side; client numbers are never trusted
    known_criteria = {c.id for c in cfg.criteria}
    known_typologies = {t.id for t in cfg.typologies}
    # Drop unknown keys and non-finite weights rather than forwarding caller-supplied
    # strings into an LLM prompt.
    weights = {k: float(v) for k, v in req.weights.items()
               if k in known_criteria and -1e6 < float(v) < 1e6}
    ranking = [t for t in req.ranking if t in known_typologies]
    return explain(cfg, get_provider(), a, weights, ranking)


@api.get("/work-backwards/{parcel_id}", summary="What would have to change to hit a target")
def work_backwards_route(parcel_id: str = PARCEL_ID,
                         typology: str = Query(max_length=_API.id_param_max_chars),
                         units: int = Query(ge=1, le=_API.work_backwards_max_units),
                         target_ami_pct: float = Query(gt=0, le=_API.target_ami_pct_max)) -> dict:
    cfg = get_config()
    if typology not in {t.id for t in cfg.typologies}:
        raise HTTPException(400, "unknown typology")
    return work_backwards(cfg, _parcel(parcel_id), typology, units, target_ami_pct)


@api.get("/unknowns", summary="Placeholders, unverified sources and unreviewed districts")
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
        "pipeline": json.loads(report_path.read_text(encoding="utf-8")) if report_path.exists() else None,
    }


app.include_router(api, prefix="/api")
# Same routes without the prefix, so the app answers whether or not the platform
# strips /api before invoking the function. Harmless locally, and it turns a
# class of deploy failure into a non-event.
app.include_router(api)
