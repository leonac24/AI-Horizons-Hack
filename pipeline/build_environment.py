"""Audit coverage of the checked-in environmental models across the parcel index.

Run after a source refresh or parcel rebuild: python -m pipeline.build_environment.
The compact model tables are used directly by the API; envelopes are not copied
22,000 times into the parcel artifact.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from datetime import UTC, datetime

from core.artifact_files import replace_text
from core.config import ROOT, load_config
from core.environment_evidence import (
    analysis_artifact_paths,
    artifact_digest,
    environment_model_paths,
    parcel_environment_inputs,
)
from core.environment_model import environment_defaults_from_config


def build_environment_coverage() -> dict:
    cfg = load_config()
    processed = ROOT / "data" / "processed"
    payload = json.loads((processed / "parcels.json").read_text(encoding="utf-8"))
    parcels = payload["parcels"]
    for line in (processed / "parcel_context.jsonl").read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        if row["id"] in parcels:
            parcels[row["id"]].update(row)
    evidence_path = processed / "parcel_evidence.jsonl"
    if evidence_path.exists():
        for line in evidence_path.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            parcel = parcels.setdefault(row["id"], {"id": row["id"]})
            parcel.update(row.get("parcel") or {})
            parcel["evidence"] = row.get("evidence") or {}
    counts: dict[str, Counter] = {}
    examples: dict[str, dict] = {}
    defaults = environment_defaults_from_config(cfg, cfg.typologies[0].id)
    for parcel in parcels.values():
        envelopes = {**defaults, **parcel_environment_inputs(parcel, cfg.typologies[0].id)}
        for key, envelope in envelopes.items():
            if not isinstance(envelope, dict):
                continue
            status = envelope.get("evidence_tier", "unknown")
            if envelope.get("value") is None:
                status = "unavailable"
            counts.setdefault(key, Counter())[status] += 1
            examples.setdefault(f"{key}:{status}", {"parcel_id": parcel["id"], "envelope": envelope})
    result = {
        "config_hash": cfg.hash,
        "runtime_evidence_hash": artifact_digest(analysis_artifact_paths()),
        "record_count": len(parcels),
        "typologies_modeled": [typ.id for typ in cfg.typologies],
        "model_artifacts": {
            str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in environment_model_paths()
        },
        "coverage": {key: dict(value) for key, value in sorted(counts.items())},
        "examples": examples,
        "limitations": "Coverage includes explicitly disclosed geographic and typology proxy estimates; it is not observation coverage or sewer capacity.",
    }
    replace_text(processed / "environment_coverage.json", json.dumps(result, indent=2) + "\n")
    return result


def refresh_analysis_metadata() -> None:
    """Record an environment-only refresh without relabeling parcel sources.

    No parcel values, PINs, locations or source vintages change here. Preserve
    the original parcel-build config hash independently of the active analysis
    configuration so this refresh remains auditable.
    """
    cfg = load_config()
    processed = ROOT / "data" / "processed"
    path = processed / "parcels.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload.setdefault("parcel_source_config_hash", payload.get("config_hash"))
    payload["config_hash"] = cfg.hash
    payload["analysis_refresh"] = {
        "scope": "environment models and declared analysis scenarios; parcel sources preserved",
        "as_of": datetime.now(UTC).isoformat(),
    }
    replace_text(path, json.dumps(payload))
    from pipeline.context_fallbacks import build as build_context
    from pipeline.planning_estimates import build as build_planning

    build_context()
    build_planning()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--refresh-metadata", action="store_true",
                        help="record an analysis-only config refresh, preserving parcel source values/vintages")
    args = parser.parse_args()
    if args.refresh_metadata:
        refresh_analysis_metadata()
    result = build_environment_coverage()
    report_path = ROOT / "data" / "processed" / "pipeline_report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    if args.refresh_metadata:
        report.setdefault("parcel_source_config_hash", report.get("config_hash"))
        report["config_hash"] = result["config_hash"]
        report["analysis_refresh_scope"] = "environment models and declared analysis scenarios; parcel sources preserved"
    report["environment"] = result["coverage"]
    report["environment_runtime_evidence_hash"] = result["runtime_evidence_hash"]
    replace_text(report_path, json.dumps(report, indent=2) + "\n")
    print(json.dumps({"record_count": result["record_count"], "coverage": result["coverage"]}, indent=2))
