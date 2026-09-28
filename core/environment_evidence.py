"""Resolve checked-in environmental models without network access at request time."""

from __future__ import annotations

import hashlib
from pathlib import Path

from core.config import ROOT


def environment_model_paths() -> tuple[Path, ...]:
    """Every compact source/model artifact that changes an analysis result."""
    return tuple(sorted((ROOT / "data" / "models").rglob("*.json")))


def analysis_artifact_paths() -> tuple[Path, ...]:
    processed = ROOT / "data" / "processed"
    return (
        processed / "parcels.json", processed / "parcel_context.jsonl",
        processed / "parcel_evidence.jsonl", processed / "valid_parcel_sales.jsonl",
        *environment_model_paths(),
    )


def artifact_digest(paths: tuple[Path, ...]) -> str:
    digest = hashlib.sha256()
    for path in paths:
        if not path.exists():
            continue
        digest.update(str(path.relative_to(ROOT)).encode())
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
    return digest.hexdigest()


def parcel_environment_inputs(parcel: dict, typology_id: str | None = None) -> dict:
    """Return sourced model envelopes, with supplied parcel evidence taking priority.

    The pipeline modules' query functions only read compact checked-in snapshots.
    Their download/refresh operations are offline CLI operations, never API work.
    """
    from pipeline.carbon_geography import build_geographic_inputs
    from pipeline.overflow_context import build_overflow_inputs

    result = {**build_geographic_inputs(parcel), **build_overflow_inputs(parcel)}
    if typology_id is not None:
        from pipeline.carbon_prototypes import build_prototype_inputs

        result.update(build_prototype_inputs(typology_id, allow_missing=True))
    for key, envelope in (parcel.get("evidence") or {}).items():
        if key in result and (
            not isinstance(envelope, dict)
            or envelope.get("value") is None
            or envelope.get("provenance") == "placeholder"
        ):
            continue
        result[key] = envelope
    return result


def declared_overrides(inputs: dict, overrides: dict[str, float]) -> dict:
    """Keep a planner's explicit numeric override visible as an assumption."""
    result = dict(inputs)
    for key, value in overrides.items():
        if key not in result:
            continue
        result[key] = {
            "unit": result[key].get("unit"), "value": value, "low": value, "high": value,
            "provenance": "assumption", "evidence_tier": "user_declared_scenario",
            "interval_type": "declared_point", "source_ids": [],
            "geography": "user-declared scenario", "as_of": None,
            "limitations": "User-supplied scenario value; not independently verified.",
        }
        result[key].pop("by_typology", None)
    # A scalar decline override intentionally replaces the named grid path.
    if "grid_decarbonization_per_yr" in overrides or "grid_kgco2e_per_kwh" in overrides:
        result.pop("grid_kgco2e_by_year", None)
    return result
