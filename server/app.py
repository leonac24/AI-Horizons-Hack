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
from core.environment_evidence import (
    analysis_artifact_paths,
    artifact_digest,
    parcel_environment_inputs,
)
from core.environment_model import environment_defaults_from_config
from core.next_steps import Step, StepKind
from core.next_steps import build as build_next_steps
from core.plan import Placement, PlanResult, analyze_plan
from core.zoning import covered_bases, load_rules
from server import lot_search
from server.ask import ask
from server.draft import draft
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
PARCEL_CONTEXT_FILE = ROOT / "data" / "processed" / "parcel_context.jsonl"
PARCEL_EVIDENCE_FILE = ROOT / "data" / "processed" / "parcel_evidence.jsonl"
VALID_SALES_FILE = ROOT / "data" / "processed" / "valid_parcel_sales.jsonl"
LAYA_EVIDENCE_FILE = ROOT / "dev" / "laya" / "compiled" / "laya_evidence.json"

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
    """Fixed-window limiter for the endpoints that cost money per call.

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
def _llm_limiter() -> _RateLimiter:
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
def _index() -> dict:
    return _index_cached(_evidence_hash())


@lru_cache(maxsize=2)
def _index_cached(evidence_hash: str) -> dict:
    if not PARCELS_FILE.exists():
        log.warning("no parcel index at %s — serving an empty index", PARCELS_FILE)
        return {"parcels": {}, "suggested": []}
    payload = json.loads(PARCELS_FILE.read_text(encoding="utf-8"))
    if PARCEL_CONTEXT_FILE.exists():
        for line in PARCEL_CONTEXT_FILE.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            parcel_id = row.pop("id")
            parcel = payload["parcels"].get(parcel_id)
            if parcel is not None:
                parcel.update(row)
    if PARCEL_EVIDENCE_FILE.exists():
        seen: set[str] = set()
        for line in PARCEL_EVIDENCE_FILE.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            parcel_id = row["id"]
            if parcel_id in seen:
                raise ValueError(f"duplicate parcel evidence PIN: {parcel_id}")
            seen.add(parcel_id)
            parcel = payload["parcels"].setdefault(parcel_id, {"id": parcel_id})
            parcel.update(row.get("parcel") or {})
            parcel["evidence"] = row.get("evidence") or {}
        payload["evidence_record_count"] = len(seen)
        payload["evidence_manifest_hash"] = evidence_hash
    return payload


def _evidence_hash() -> str:
    """Hash the artifact actually served; changing only data invalidates analysis."""
    paths = analysis_artifact_paths()
    if not any(path.exists() for path in paths):
        return "none"
    version = tuple((str(path.relative_to(ROOT)), path.stat().st_mtime_ns, path.stat().st_size)
                    for path in paths if path.exists())
    return _evidence_hash_for_version(version)


@lru_cache(maxsize=8)
def _evidence_hash_for_version(version: tuple[tuple[str, int, int], ...]) -> str:
    return artifact_digest(analysis_artifact_paths())


@lru_cache(maxsize=2)
def _sales_index(evidence_hash: str) -> list[dict]:
    """Normalized qualifying sales are loaded once, then passed only to models."""
    if not VALID_SALES_FILE.exists():
        return []
    return [json.loads(line) for line in VALID_SALES_FILE.read_text(encoding="utf-8").splitlines()
            if line.strip()]


def _parcel(parcel_id: str) -> dict:
    p = _index()["parcels"].get(parcel_id)
    if p is None:
        raise HTTPException(404, "no vacant parcel with that id in the index")
    return p


@lru_cache(maxsize=1)
def _laya_evidence() -> dict | None:
    """Read only the artifact created locally; deployment never loads Laya."""
    if not LAYA_EVIDENCE_FILE.exists():
        return None
    return json.loads(LAYA_EVIDENCE_FILE.read_text(encoding="utf-8"))


@lru_cache(maxsize=_API.analysis_cache_entries)
def _analysis_cached(parcel_id: str, config_hash: str, evidence_hash: str) -> Analysis:
    result = analyze(get_config(), _parcel(parcel_id), sale_candidates=_sales_index(evidence_hash))
    result.evidence_manifest_hash = evidence_hash
    return result


def _analysis(parcel_id: str) -> Analysis:
    return _analysis_cached(parcel_id, get_config().hash, _evidence_hash())


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
    index = _index()
    return {"ok": True, "config_hash": cfg.hash, "evidence_manifest_hash": _evidence_hash(),
            "parcel_index_config_hash": index.get("config_hash"),
            "parcel_index_config_matches": index.get("config_hash") == cfg.hash,
            "parcels": len(index["parcels"]),
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


@api.get("/next-steps/{parcel_id}", summary="What to do next on one lot, and who to contact")
def next_steps(request: Request, response: Response, parcel_id: str = PARCEL_ID) -> list[Step]:
    steps = build_next_steps(get_config(), _analysis(parcel_id))
    if _conditional(request, response, [s.model_dump(mode="json") for s in steps]):
        return Response(status_code=304)  # type: ignore[return-value]
    return steps


class DraftRequest(BaseModel):
    parcel_id: str = ParcelId
    step_id: StepKind


@api.post("/draft", summary="Draft outreach for one next step; nothing is sent")
def draft_route(req: DraftRequest, request: Request) -> dict:
    cfg = get_config()
    a = _analysis(req.parcel_id)
    step = next((s for s in build_next_steps(cfg, a) if s.id == req.step_id), None)
    if step is None:
        raise HTTPException(404, "that step does not apply to this lot")
    _spend(request)
    return draft(cfg, get_provider(), a, step)


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
        return analyze_plan(cfg, _parcel(parcel_id), req.placements,
                            sale_candidates=_sales_index(_evidence_hash()))
    except ValueError as e:
        raise HTTPException(422, str(e)) from e


class ExplainRequest(BaseModel):
    """Weights and ranking are the caller's *values*. They are echoed into the
    prompt but never trusted as evidence: the server recomputes every number.
    """

    parcel_id: str = ParcelId
    weights: dict[str, float] = Field(default_factory=dict)
    ranking: list[str] = Field(default_factory=list)


def _values(cfg, weights: dict[str, float], ranking: list[str]) -> tuple[dict[str, float], list[str]]:
    """Cap, then filter the caller's weights and ranking to known ids. Unknown
    keys and non-finite weights are dropped rather than forwarded into a prompt."""
    limits = cfg.app.api
    if len(weights) > limits.explain_max_weights or len(ranking) > limits.explain_max_ranking:
        raise HTTPException(413, "too many weights or ranking entries")
    known_criteria = {c.id for c in cfg.criteria}
    known_typologies = {t.id for t in cfg.typologies}
    return ({k: float(v) for k, v in weights.items() if k in known_criteria and -1e6 < float(v) < 1e6},
            [t for t in ranking if t in known_typologies])


def _spend(request: Request) -> None:
    if not _llm_limiter().check(_client_key(request)):
        raise HTTPException(429, "too many AI requests; try again shortly")


@api.post("/explain", summary="Grounded prose over already-computed metrics")
def explain_route(req: ExplainRequest, request: Request) -> dict:
    cfg = get_config()
    weights, ranking = _values(cfg, req.weights, req.ranking)
    _spend(request)
    a = _analysis(req.parcel_id)  # recomputed server-side; client numbers are never trusted
    return explain(cfg, get_provider(), a, weights, ranking)


class AskRequest(ExplainRequest):
    question: str = Field(min_length=1, max_length=_API.ask_question_max_chars)


@api.post("/ask", summary="Answer a question about one lot from its computed metrics")
def ask_route(req: AskRequest, request: Request) -> dict:
    cfg = get_config()
    weights, ranking = _values(cfg, req.weights, req.ranking)
    _spend(request)
    return ask(cfg, get_provider(), _analysis(req.parcel_id), weights, ranking, req.question.strip())


class LotSearchRequest(BaseModel):
    query: str = Field(min_length=_API.search_query_min_chars, max_length=_API.lot_search_query_max_chars)


@lru_cache(maxsize=1)
def _search_vocab() -> dict:
    return lot_search.vocab(list(_index()["parcels"].values()))


@api.post("/parcels/ask", summary="Turn a plain-English request into map filters")
def lot_search_route(req: LotSearchRequest, request: Request) -> dict:
    _spend(request)
    out = lot_search.search(get_config(), get_provider(), list(_index()["parcels"].values()), _search_vocab(),
                            req.query.strip())
    if out.get("ok"):
        out["results"] = [_summary(p) for p in out["results"]]
    return out


@api.get("/work-backwards/{parcel_id}", summary="What would have to change to hit a target")
def work_backwards_route(parcel_id: str = PARCEL_ID,
                         typology: str = Query(max_length=_API.id_param_max_chars),
                         units: int = Query(ge=1, le=_API.work_backwards_max_units),
                         target_ami_pct: float = Query(gt=0, le=_API.target_ami_pct_max)) -> dict:
    cfg = get_config()
    if typology not in {t.id for t in cfg.typologies}:
        raise HTTPException(400, "unknown typology")
    return work_backwards(cfg, _parcel(parcel_id), typology, units, target_ami_pct,
                          sale_candidates=_sales_index(_evidence_hash()))


@api.get("/unknowns", summary="Placeholders, unverified sources and unreviewed districts")
def unknowns() -> dict:
    """Everything the tool does not know yet — feeds the 'What we don't know' page."""
    cfg = get_config()
    rules = load_rules(cfg)
    parcels = _index()["parcels"].values()
    by_district = Counter(p.get("zoning") or "(no district)" for p in parcels)

    def base(code: str) -> str | None:
        return cfg.zoning.district_code.split(code)[0]

    covered_b, human_b = covered_bases(cfg, rules), covered_bases(cfg, rules, human_only=True)
    total = sum(by_district.values()) or 1
    covered = sum(n for d, n in by_district.items() if base(d) in covered_b)
    human = sum(n for d, n in by_district.items() if base(d) in human_b)
    report_path = ROOT / "data" / "processed" / "pipeline_report.json"
    evidence_coverage = _environment_coverage(cfg.hash, _evidence_hash())
    return {
        "placeholder_assumptions": [
            {"id": k, "unit": a.unit, "rationale": a.rationale, "source": a.source}
            for k, a in cfg.assumptions.items() if a.provenance == "placeholder"],
        "unverified_sources": [
            {"id": k, "name": s.name, "note": s.note} for k, s in cfg.sources.sources.items() if s.verified is False],
        "uncovered_districts": [
            {"district": d, "vacant_parcels": n} for d, n in by_district.most_common() if base(d) not in covered_b],
        "vacant_parcels": total,
        "share_covered_by_rules": round(covered / total, 4),
        "share_covered_by_human_reviewed_rules": round(human / total, 4),
        "require_human_review": cfg.zoning.require_human_review,
        "pipeline": json.loads(report_path.read_text(encoding="utf-8")) if report_path.exists() else None,
        "evidence_manifest_hash": _evidence_hash(),
        "evidence_record_count": _index().get("evidence_record_count", 0),
        "evidence_coverage": evidence_coverage,
    }


@lru_cache(maxsize=2)
def _environment_coverage(config_hash: str, evidence_hash: str) -> dict:
    path = ROOT / "data" / "processed" / "environment_coverage.json"
    if path.exists():
        report = json.loads(path.read_text(encoding="utf-8"))
        if report.get("config_hash") == config_hash and report.get("runtime_evidence_hash") == evidence_hash:
            return report["coverage"]
    # Source refreshes can precede the offline audit. Recompute once per actual
    # data/config hash rather than serve stale counts or rescan every request.
    cfg = get_config()
    defaults = environment_defaults_from_config(cfg, cfg.typologies[0].id)
    counts: dict[str, Counter[str]] = {}
    for parcel in _index()["parcels"].values():
        envelopes = {**defaults, **parcel_environment_inputs(parcel, cfg.typologies[0].id)}
        for field, envelope in envelopes.items():
            if not isinstance(envelope, dict):
                continue
            tier = str(envelope.get("evidence_tier") or "unknown") if envelope.get("value") is not None else "unavailable"
            counts.setdefault(field, Counter())[tier] += 1
    return {field: dict(tiers) for field, tiers in sorted(counts.items())}


@api.get("/evidence", summary="Locally compiled document leads; not verified findings")
def evidence(topic: str | None = Query(None, max_length=_API.id_param_max_chars),
             offset: int = Query(0, ge=0), limit: int = Query(20, ge=1, le=100)) -> dict:
    topics = get_config().app.evidence.topics
    topic = topic or next(iter(topics))
    if topic not in topics:
        raise HTTPException(422, "unknown evidence topic")
    index = _laya_evidence()
    if index is None:
        return {"compiled": False, "documents": 0, "passages": 0, "total": 0, "items": []}
    items = [p for p in index.get("passages", []) if p.get("topic") == topic]
    items.sort(key=lambda p: (p.get("document", ""), p.get("page") or 0, p.get("part", 0)))
    return {"compiled": True, "documents": len(index.get("documents", [])),
            "passages": len(index.get("passages", [])), "total": len(items),
            "items": items[offset:offset + limit]}


app.include_router(api, prefix="/api")
# Same routes without the prefix, so the app answers whether or not the platform
# strips /api before invoking the function. Harmless locally, and it turns a
# class of deploy failure into a non-event.
app.include_router(api)
