"""Extract sourced numeric candidates from local documents for explicit adoption.

Laya routes passages; Claude returns structured candidates. Quote, unit, source,
and schema checks are deterministic. Results are proposals only and never alter
assumptions or parcel metrics automatically. Zoning rules use the separate,
table-aware ``pipeline.zoning.extract`` workflow.
"""

from __future__ import annotations

import argparse
import json
import math
import os
from datetime import UTC, datetime
from pathlib import Path

import yaml

from dev.laya.compile import QUESTIONS, ROOT, chunks, discover, read_pages, sha256, sources

OUT = ROOT / "dev" / "laya" / "compiled" / "metric_candidates.json"
INPUT_IDS = {
    "cost": {"annual_capital_cost_share", "operating_cost_per_unit_month"},
    "carbon": {
        "embodied_kgco2e_psf", "operational_kwh_psf_yr", "grid_decarbonization_per_yr",
        "kgco2e_per_vmt",
    },
    "housing_need": {"tract_median_household_income", "tract_renter_cost_burden_share"},
    "transit_jobs": {"jobs_access_index", "vmt_per_household_yr"},
    "sewer": {"sewer_stress_index"},
    "site": {"lot_depth_to_frontage_ratio"},
}


def _tool_schema(ids: set[str]) -> dict:
    return {
        "name": "report_evidence",
        "description": "Report only directly stated numeric evidence from the supplied passage.",
        "input_schema": {
            "type": "object", "additionalProperties": False,
            "properties": {"candidates": {
                "type": "array",
                "items": {
                    "type": "object", "additionalProperties": False,
                    "properties": {
                        "assumption_id": {"type": "string", "enum": sorted(ids)},
                        "value": {"type": "number"},
                        "unit": {"type": "string"},
                        "geography": {"type": "string"},
                        "period": {"type": "string"},
                        "quote": {"type": "string"},
                        "table_or_section": {"type": "string"},
                    },
                    "required": ["assumption_id", "value", "unit", "geography", "period",
                                 "quote", "table_or_section"],
                }
            }}, "required": ["candidates"]
        },
    }


def _normalize(text: str) -> str:
    return " ".join(text.split())


def validate_candidate(row: dict, passage: str, source_id: str, source_registry: dict,
                       assumptions: dict) -> tuple[dict | None, str | None]:
    aid = row.get("assumption_id")
    if aid not in assumptions or aid not in {x for ids in INPUT_IDS.values() for x in ids}:
        return None, "unknown_or_nonextractable_assumption"
    assumption = assumptions[aid]
    if assumption.get("provenance") != "placeholder":
        return None, "assumption_is_not_placeholder"
    if source_id not in source_registry:
        return None, "unknown_source_id"
    try:
        value = float(row["value"])
    except (KeyError, TypeError, ValueError):
        return None, "invalid_numeric_value"
    if not math.isfinite(value):
        return None, "non_finite_numeric_value"
    if row.get("unit", "").strip().lower() != assumption.get("unit", "").strip().lower():
        return None, "unit_mismatch"
    quote = row.get("quote", "").strip()
    if not quote or _normalize(quote) not in _normalize(passage):
        return None, "quote_not_found_verbatim"
    geography = row.get("geography")
    period = row.get("period")
    section = row.get("table_or_section")
    if not all(isinstance(x, str) and x.strip() for x in (geography, period, section)):
        return None, "missing_geography_or_period"
    return {
        "assumption_id": aid, "value": value, "unit": assumption["unit"],
        "geography": geography.strip(), "period": period.strip(),
        "quote": quote, "table_or_section": section.strip(),
        "source_id": source_id, "source_name": source_registry[source_id].get("name", source_id),
        "source_url": source_registry[source_id].get("url"),
        "status": "candidate_unapplied",
    }, None


def extract(predict_topic, client, model: str) -> dict:
    registry = sources()
    assumptions_doc = yaml.safe_load(
        (ROOT / "data/config/assumptions.yaml").read_text(encoding="utf-8")
    )
    assumptions = assumptions_doc["assumptions"]
    result = {
        "schema_version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "models": {"routing": "laya", "extraction": model},
        "policy": (
            "Candidates are not applied. Exact quote and unit checks are required; "
            "source scope is still an explicit adoption decision."
        ),
        "documents": [], "candidates": [], "rejected": [],
    }
    for source_id, path in discover():
        if source_id not in registry:
            raise ValueError(f"Unknown source id {source_id!r}: {path}")
        raw = path.read_bytes()
        rel = path.relative_to(ROOT).as_posix()
        pages = read_pages(path)
        count = 0
        for page_no, page in enumerate(pages, 1):
            for part, passage in enumerate(chunks(page), 1):
                try:
                    topic = predict_topic(passage, QUESTIONS)
                except Exception as exc:
                    result["rejected"].append({
                        "document": rel, "page": page_no, "part": part,
                        "reason": f"laya_routing_error:{type(exc).__name__}",
                    })
                    continue
                eligible = INPUT_IDS.get(topic, set())
                if not eligible:
                    continue
                response = client.messages.create(
                    model=model, max_tokens=1200,
                    system=("Extract only numeric claims explicitly stated in this source passage. "
                            "Do not calculate, infer a Pittsburgh value from a national statistic, "
                            "or convert units. Distinguish averages, ranges, per-unit rates, and "
                            "geographic/temporal scopes. Exclude claims that do not directly map "
                            "to an allowed placeholder. Zoning laws are handled elsewhere."),
                    messages=[{"role": "user", "content": f"Passage:\n{passage}"}],
                    tools=[_tool_schema(eligible)],
                    tool_choice={"type": "tool", "name": "report_evidence"},
                )
                tool = next((block for block in response.content if block.type == "tool_use"), None)
                if tool is None:
                    result["rejected"].append({
                        "document": rel, "page": page_no, "part": part,
                        "reason": "missing_structured_output",
                    })
                    continue
                for row in tool.input.get("candidates", []):
                    candidate, reason = validate_candidate(
                        row, passage, source_id, registry, assumptions
                    )
                    provenance = {
                        "document": rel,
                        "page": page_no if path.suffix.lower() == ".pdf" else None,
                        "part": part,
                        "document_sha256": sha256(raw),
                        "passage_sha256": sha256(passage.encode()),
                    }
                    if candidate:
                        candidate.update(provenance)
                        result["candidates"].append(candidate)
                    else:
                        result["rejected"].append({
                            **provenance, "assumption_id": row.get("assumption_id"),
                            "reason": reason,
                        })
                count += 1
        result["documents"].append({
            "source_id": source_id, "path": rel,
            "sha256": sha256(raw), "eligible_passages": count,
        })
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default=os.getenv("ZONING_EXTRACT_MODEL", "claude-opus-5"))
    parser.add_argument("--output", type=Path, default=OUT)
    args = parser.parse_args()
    try:
        import anthropic
        import laya
    except ImportError as exc:
        raise SystemExit(
            "Install local dependencies: python -m pip install "
            "-r dev/laya/requirements.txt and the project runtime dependencies"
        ) from exc
    if not os.getenv("ANTHROPIC_API_KEY"):
        raise SystemExit("Set ANTHROPIC_API_KEY to run structured candidate extraction")
    router = laya.Router(max_loaded=1)
    client = anthropic.Anthropic()
    def predict_topic(text: str, questions: dict) -> str:
        prediction = router.predict(text, questions, model="typed-decisions")
        return prediction["answers"]["topic"]["choice"]

    index = extract(predict_topic, client, args.model)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(index, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(
        f"Wrote {len(index['candidates'])} unapplied candidates from "
        f"{len(index['documents'])} documents to {args.output}"
    )


if __name__ == "__main__":
    main()
