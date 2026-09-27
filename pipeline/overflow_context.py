"""Evidence envelopes for historical ALCOSAN modeled sewer-overflow context.

The checked-in outfall registry is the only runtime input: this module does not
fetch the source PDF or use GIS/network dependencies. PWSA ``CSO_SHED`` labels
join only by exact outfall ID, explicitly printed report alias, or the one
verified terminal ``-OF`` marker normalization documented with the registry.
"""

from __future__ import annotations

import json
import math
from collections import defaultdict
from collections.abc import Mapping
from functools import lru_cache
from pathlib import Path
from typing import Any

MODEL_PATH = Path(__file__).resolve().parents[1] / "data" / "models" / "alcosan_overflows.json"
ALCOSAN_SOURCE_ID = "alcosan_cwp_section4_2018"
PWSA_SOURCE_ID = "pwsa_combined_sewersheds_2018"
PWSA_SOURCE_URL = "https://data.wprdc.org/dataset/combined-sewershed"


@lru_cache(maxsize=8)
def _read_model_cached(path: str, mtime_ns: int, size: int) -> dict[str, Any]:
    """Read a model snapshot, keyed by file identity so updates invalidate it."""
    del mtime_ns, size  # Included in the cache key intentionally.
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _load_model(path: str | Path | None = None) -> dict[str, Any]:
    model_path = Path(path) if path is not None else MODEL_PATH
    stat = model_path.stat()
    return _read_model_cached(str(model_path.resolve()), stat.st_mtime_ns, stat.st_size)


def _model_indexes(model: Mapping[str, Any]) -> tuple[dict[str, list[dict]], list[dict]]:
    by_identifier: dict[str, list[dict]] = defaultdict(list)
    modeled = [
        row for row in model.get("outfalls", [])
        if row.get("model_status") == "modeled"
        and row.get("volume_million_gallons_per_year") is not None
    ]
    for row in modeled:
        key = str(row.get("outfall_id", "")).strip().upper()
        if key:
            by_identifier[key].append(row)
        for alias in row.get("report_aliases", []):
            alias_key = str(alias).strip().upper()
            if alias_key:
                by_identifier[alias_key].append(row)
    return by_identifier, modeled


def _resolve_token(token: str, by_identifier: Mapping[str, list[dict]]) -> dict | None:
    """Resolve an exact CWP ID/alias, then the verified terminal ``-OF`` form."""
    key = token.strip().upper()
    exact = by_identifier.get(key, [])
    if exact:
        return exact[0] if len(exact) == 1 else None
    with_outfall_marker = by_identifier.get(f"{key}-OF", [])
    if with_outfall_marker:
        return with_outfall_marker[0] if len(with_outfall_marker) == 1 else None
    return None


def _as_labels(value: Any) -> list[str]:
    if isinstance(value, str):
        candidates = [value]
    elif isinstance(value, (list, tuple, set)):
        candidates = [str(item) for item in value if item is not None]
    else:
        candidates = []
    labels: list[str] = []
    for candidate in candidates:
        label = candidate.strip()
        if label and label not in labels:
            labels.append(label)
    return labels


def _resolve_labels(
    labels: list[str], by_identifier: Mapping[str, list[dict]]
) -> tuple[list[dict], list[dict], list[str]]:
    """Return complete matched labels, unique rows, and unresolved tokens.

    A composite label is accepted only if every slash-delimited token resolves.
    This prevents a partially understood composite from being presented as a
    complete direct estimate.
    """
    resolved_labels: list[dict] = []
    unresolved_tokens: list[str] = []
    unique_outfalls: dict[str, dict] = {}
    for label in labels:
        tokens = [token.strip() for token in label.split("/") if token.strip()]
        matches = [_resolve_token(token, by_identifier) for token in tokens]
        if not tokens or any(match is None for match in matches):
            unresolved_tokens.extend(token for token, match in zip(tokens, matches) if match is None)
            if not tokens:
                unresolved_tokens.append(label)
            continue
        rows = [match for match in matches if match is not None]
        resolved_labels.append({"label": label, "outfalls": [row["outfall_id"] for row in rows]})
        for row in rows:
            unique_outfalls[str(row["outfall_id"]).upper()] = row
    return (
        resolved_labels,
        list(unique_outfalls.values()),
        list(dict.fromkeys(unresolved_tokens)),
    )


def _source_urls(model: Mapping[str, Any], *, include_pwsa: bool) -> list[str]:
    urls = [str(model.get("metadata", {}).get("source_url", ""))]
    if include_pwsa:
        urls.append(PWSA_SOURCE_URL)
    return [url for url in urls if url]


def _limitations(*, direct: bool, partial: bool = False, has_shed_label: bool = False) -> str:
    if direct:
        text = (
            "ALCOSAN existing-condition typical-year modeled outfall estimates are historical context, "
            "not measured present-day overflow or parcel-specific discharge. The volume is modeled "
            "annual overflow at named outfall(s), not parcel wastewater flow or added-flow contribution. "
            "The 2018 PWSA CSO_SHED "
            "label is joined only to explicitly matched outfall IDs; no nearest-outfall or distance join "
            "is used. This does not establish sewer service, pipe condition, or available capacity."
        )
        if partial:
            text += " Some parcel sewershed labels or composite tokens were unmatched; only listed matched outfalls contribute to this value."
        return text
    prefix = (
        "Regional fallback used because the parcel has a mapped PWSA CSO_SHED label but no complete exact "
        "outfall match was available."
        if has_shed_label
        else "Regional fallback used because no mapped PWSA CSO_SHED label was available for the parcel."
    )
    return (
        f"{prefix} The value is the unweighted mean of published modeled outfall annual volumes in the "
        "ingested ALCOSAN Clean Water Plan tables; low/high are the descriptive minimum and maximum "
        "outfall values, not a confidence interval. The volume is an outfall model result, not parcel "
        "wastewater flow or added-flow contribution. This is not parcel-specific overflow exposure, a "
        "current observation, or a sewer-capacity finding. No nearest-outfall or distance join is used."
    )


def build_overflow_inputs(parcel: Mapping[str, Any], *, model_path: str | Path | None = None) -> dict:
    """Return modeled overflow context and a normalized outfall-volume index.

    Direct parcel values use all unique report outfalls resolved from the
    parcel's PWSA ``combined_sewershed_ids``. If none resolve, every parcel gets
    an explicitly labeled service-area fallback. The index compares the mean
    annual volume of matched outfalls with the equal-weight mean of all
    modeled outfalls in the ingested report tables; it is not a capacity score.
    """
    parcel_data = parcel if isinstance(parcel, Mapping) else {}
    model = _load_model(model_path)
    metadata = model.get("metadata", {})
    by_identifier, modeled_outfalls = _model_indexes(model)
    volumes = [float(row["volume_million_gallons_per_year"]) for row in modeled_outfalls]
    if not volumes:
        return {}

    system_mean = math.fsum(volumes) / len(volumes)
    system_min = min(volumes)
    system_max = max(volumes)
    labels = _as_labels(parcel_data.get("combined_sewershed_ids"))
    resolved_labels, matched_outfalls, unmatched_tokens = _resolve_labels(labels, by_identifier)
    direct = bool(matched_outfalls)
    partial = direct and bool(unmatched_tokens)
    join_method = parcel_data.get("sewershed_join_method")

    if direct:
        selected_volumes = [float(row["volume_million_gallons_per_year"]) for row in matched_outfalls]
        total_volume = math.fsum(selected_volumes)
        mean_outfall_volume = math.fsum(selected_volumes) / len(selected_volumes)
        context_value = total_volume
        context_low = total_volume
        context_high = total_volume
        evidence_tier = "direct_sewershed_outfall_match"
        context_geography = (
            f"PWSA combined sewershed label(s) {', '.join(row['label'] for row in resolved_labels)}; "
            f"matched outfall(s) {', '.join(row['outfall_id'] for row in matched_outfalls)}"
        )
        index_value = mean_outfall_volume / system_mean if system_mean else None
        index_low = min(selected_volumes) / system_mean if system_mean else None
        index_high = max(selected_volumes) / system_mean if system_mean else None
        frequency_rows = [
            {"outfall_id": row["outfall_id"], "value": row["frequency_activations_per_year"]}
            for row in matched_outfalls
        ]
        duration_rows = [
            {"outfall_id": row["outfall_id"], "value": row["duration_hours_per_year"]}
            for row in matched_outfalls
        ]
        volume_rows = [
            {
                "outfall_id": row["outfall_id"],
                "value": row["volume_million_gallons_per_year"],
                "unit": "million gallons/year",
                "planning_basin": row["planning_basin"],
                "source_table": row["source_table"],
                "source_pdf_page": row.get("source_pdf_page"),
                "provenance": "modeled",
                "source_ids": [ALCOSAN_SOURCE_ID, PWSA_SOURCE_ID],
            }
            for row in matched_outfalls
        ]
        source_ids = [ALCOSAN_SOURCE_ID, PWSA_SOURCE_ID]
    else:
        context_value = system_mean
        context_low = system_min
        context_high = system_max
        evidence_tier = "regional_modeled_fallback"
        context_geography = "ALCOSAN modeled CSO outfalls in the ingested Clean Water Plan service-area tables"
        index_value = 1.0
        index_low = system_min / system_mean if system_mean else None
        index_high = system_max / system_mean if system_mean else None
        frequency_rows = []
        duration_rows = []
        volume_rows = []
        source_ids = [ALCOSAN_SOURCE_ID]
        if labels:
            source_ids.append(PWSA_SOURCE_ID)

    geography = context_geography
    if join_method:
        geography += f" (parcel join method: {join_method})"
    base = {
        "value": context_value,
        "low": context_low,
        "high": context_high,
        "unit": "million gallons/year",
        "provenance": "modeled",
        "evidence_tier": evidence_tier,
        "interval_type": "point_estimate" if direct else "regional_reference_spread",
        "measure_definition": (
            "sum of the ALCOSAN modeled typical-year annual overflow volumes for unique exact-matched outfalls"
            if direct
            else "unweighted regional mean of ALCOSAN modeled typical-year annual overflow volume per outfall"
        ),
        "geography": geography,
        "source_ids": source_ids,
        "source_urls": _source_urls(model, include_pwsa=bool(labels)),
        "as_of": metadata.get("report_vintage", "2018 report vintage"),
        "model_vintage": metadata.get("report_vintage"),
        "model_scenario": metadata.get("model_scenario"),
        "model_period": metadata.get("model_period"),
        "annual_frequency_activations_per_year_by_outfall": frequency_rows,
        "annual_duration_hours_per_year_by_outfall": duration_rows,
        "annual_volume_million_gallons_by_outfall": volume_rows,
        "resolved_sewershed_labels": resolved_labels,
        "unmatched_sewershed_tokens": unmatched_tokens,
        "regional_fallback_method": None if direct else {
            "statistic": "unweighted arithmetic mean across modeled outfall records",
            "outfall_count": len(volumes),
            "reference_mean_million_gallons_per_year": system_mean,
            "reference_min_million_gallons_per_year": system_min,
            "reference_max_million_gallons_per_year": system_max,
            "range_is_confidence_interval": False,
        },
        "limitations": _limitations(direct=direct, partial=partial, has_shed_label=bool(labels)),
        "confirmation_needed": "Verify current utility service, outfall linkage, and available capacity with PWSA/ALCOSAN.",
    }

    stress = {
        "value": index_value,
        "low": index_low,
        "high": index_high,
        "unit": "ratio to equal-weight mean modeled CSO outfall volume",
        "provenance": "modeled",
        "evidence_tier": evidence_tier,
        "interval_type": "matched_outfall_spread" if direct else "regional_reference_spread",
        "geography": geography,
        "source_ids": source_ids,
        "source_urls": _source_urls(model, include_pwsa=bool(labels)),
        "as_of": metadata.get("report_vintage", "2018 report vintage"),
        "model_vintage": metadata.get("report_vintage"),
        "model_scenario": metadata.get("model_scenario"),
        "model_period": metadata.get("model_period"),
        "normalization": {
            "formula": (
                "arithmetic mean of matched outfall typical-year annual volumes / equal-weight mean annual volume across all modeled outfalls in ingested CWP tables"
            ),
            "reference_outfall_count": len(volumes),
            "reference_mean_million_gallons_per_year": system_mean,
            "reference_scope": "modeled outfall rows in the ingested ALCOSAN Clean Water Plan per-outfall CSO tables; not a city or parcel-weighted mean",
        },
        "limitations": (
            "Contextual model ratio only; it is not measured sewer stress, system capacity, pipe condition, "
            "or a parcel-specific impact. The reference is an equal-weight mean outfall volume across the "
            "ingested ALCOSAN report tables, not a city or parcel-weighted average."
            if direct
            else "Regional fallback index equals 1 by definition because no complete direct outfall match exists; low/high show the model outfall range relative to the system mean and are not a confidence interval or parcel estimate."
        ),
    }
    return {"sewer_overflow_context": base, "sewer_stress_index": stress}
