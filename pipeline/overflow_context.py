"""Evidence envelopes for historical ALCOSAN modeled sewer-overflow context.

The checked-in outfall registry is the only runtime input: this module does not
fetch the source PDF or use GIS/network dependencies. PWSA ``CSO_SHED`` labels
join only by exact outfall ID, explicitly printed report alias, or the one
verified terminal ``-OF`` marker normalization documented with the registry.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import subprocess
from collections import defaultdict
from collections.abc import Mapping
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

MODEL_PATH = Path(__file__).resolve().parents[1] / "data" / "models" / "alcosan_overflows.json"
ALCOSAN_SOURCE_ID = "alcosan_cwp_section4_2018"
PWSA_SOURCE_ID = "pwsa_combined_sewersheds"
PWSA_SOURCE_URL = "https://data.wprdc.org/dataset/combined-sewershed"
_PDF_TEXT_TOOL = "pdftotext"
_SOURCE_TABLE_PATTERN = re.compile(r"\bTable\s+(4-\d+)\s*:", re.IGNORECASE)
_FOOTER_PATTERN = re.compile(r"^\s*4\s*-\s*(\d+)\s*$")
_CELL_NUMBER_PATTERN = re.compile(r"\(\d+\)|(?<![A-Za-z])\d[\d,]*(?:\.\d+)?")


def _compact_label(value: str) -> str:
    return re.sub(r"\s+", "", value).upper()


def _table_region(lines: list[str], table_id: str) -> tuple[int, int, int] | None:
    """Return title line, body start, and body end for one printed table page."""
    title = next(
        (
            index for index, line in enumerate(lines)
            if re.search(rf"\bTable\s+{re.escape(table_id)}\s*:", line, re.IGNORECASE)
        ),
        None,
    )
    if title is None:
        return None
    end = len(lines)
    for index in range(title + 1, len(lines)):
        if re.match(r"^\s*\*?\s*Note\b", lines[index], re.IGNORECASE):
            end = index
            break
        if _FOOTER_PATTERN.match(lines[index]):
            end = index
            break
        if re.match(r"^\s*\d+\.\d+(?:\.\d+)?\s+", lines[index]):
            end = index
            break
    return title, title + 1, end


def _row_variants(row: Mapping[str, Any]) -> list[str]:
    """Stable table keys include IDs and the report's printed alias labels."""
    variants = [str(row.get("outfall_id", ""))]
    source_label = str(row.get("source_outfall_label", ""))
    if source_label:
        variants.append(source_label.split("(", 1)[0].strip())
    variants.extend(str(alias) for alias in row.get("report_aliases", []))
    return list(dict.fromkeys(value for value in variants if value))


def _row_start_candidates(
    lines: list[str], start: int, end: int, row: Mapping[str, Any]
) -> list[int]:
    variants = [_compact_label(value) for value in _row_variants(row)]
    candidates: list[int] = []
    for index in range(start, end):
        first_line = _compact_label(lines[index])
        if not first_line:
            continue
        # pdftotext -raw may wrap a long outfall ID across lines (for example
        # M4400_-OSC- / M-02OF). Reassemble at most three physical text lines.
        combined = _compact_label(" ".join(lines[index:min(index + 3, end)]))
        if any(
            combined.startswith(variant)
            and (first_line.startswith(variant) or variant.startswith(first_line))
            and len(first_line) >= 4
            for variant in variants
        ):
            candidates.append(index)
    return candidates


def _remove_row_label(row_lines: list[str], row: Mapping[str, Any]) -> list[str]:
    """Remove the printed label while preserving any owner and annual cells."""
    variants = sorted(
        [str(row.get("source_outfall_label", "")), str(row.get("outfall_id", "")),
         *(str(alias) for alias in row.get("report_aliases", []))],
        key=len,
        reverse=True,
    )
    for variant in (value for value in variants if value):
        expected = _compact_label(variant)
        consumed = 0
        remainder: list[str] = []
        failed = False
        for line_index, line in enumerate(row_lines):
            offset = 0
            while offset < len(line):
                char = line[offset]
                offset += 1
                if char.isspace():
                    continue
                if consumed == len(expected) or char.upper() != expected[consumed]:
                    failed = True
                    break
                consumed += 1
                if consumed == len(expected):
                    remainder.append(line[offset:])
                    remainder.extend(row_lines[line_index + 1:])
                    return remainder
            if failed:
                break
    return row_lines


def _read_annual_cells(row_lines: list[str], row: Mapping[str, Any]) -> list[str]:
    """Read the three cells after the outfall label, ignoring numeric footnotes."""
    for line in _remove_row_label(row_lines, row):
        tokens = _CELL_NUMBER_PATTERN.findall(line)
        plain = [token for token in tokens if not re.fullmatch(r"\(\d+\)", token)]
        placeholders = [token for token in tokens if re.fullmatch(r"\(\d+\)", token)]
        if len(plain) >= 3:
            return plain[:3]
        if not plain and len(placeholders) >= 3:
            return placeholders[:3]
    return []


def _table_row_locations(
    pages: list[str], rows: list[dict[str, Any]]
) -> dict[str, tuple[int, int, int]]:
    """Find each registered outfall's printed table page and row start.

    The registry supplies stable row identities and curated footnote aliases;
    all frequency, duration, volume, model status, and page values are rebuilt
    from the PDF text. Ambiguous or missing identities fail closed.
    """
    locations: dict[str, tuple[int, int, int]] = {}
    for row in rows:
        table_id = str(row["source_table"])
        candidates: list[tuple[int, int, int]] = []
        for page_number, page_text in enumerate(pages, start=1):
            lines = page_text.splitlines()
            region = _table_region(lines, table_id)
            if region is None:
                continue
            _, body_start, body_end = region
            for line_index in _row_start_candidates(lines, body_start, body_end, row):
                candidates.append((page_number, line_index, body_end))
        # Some PDF text layers repeat a caption or identity. Accept only one
        # row start; never guess which table occurrence is the data row.
        if len(candidates) != 1:
            raise ValueError(
                f"Expected one table-row match for {row['outfall_id']} in {table_id}, "
                f"found {len(candidates)}"
            )
        locations[str(row["outfall_id"])] = candidates[0]
    return locations


def _parse_pdf_text(model: dict[str, Any], pdf_text: str) -> dict[str, Any]:
    pages = pdf_text.split("\f")
    if pages and not pages[-1].strip():
        pages.pop()
    expected_pages = int(model["metadata"].get("source_pdf_pages", 0))
    if expected_pages and len(pages) != expected_pages:
        raise ValueError(f"Expected {expected_pages} PDF pages, extracted {len(pages)}")

    rows = model["outfalls"]
    locations = _table_row_locations(pages, rows)
    by_page: dict[int, list[tuple[str, int, int]]] = defaultdict(list)
    for outfall_id, (page_number, line_index, region_end) in locations.items():
        by_page[page_number].append((outfall_id, line_index, region_end))

    row_by_id = {str(row["outfall_id"]): row for row in rows}
    for page_number, page_rows in by_page.items():
        lines = pages[page_number - 1].splitlines()
        ordered = sorted(page_rows, key=lambda row_location: row_location[1])
        for row_index, (outfall_id, line_index, region_end) in enumerate(ordered):
            next_row_start = (
                ordered[row_index + 1][1]
                if row_index + 1 < len(ordered)
                else region_end
            )
            row_lines = lines[line_index:next_row_start]
            row_text = " ".join(row_lines).strip()
            row = row_by_id[outfall_id]
            footer_page = next(
                (
                    int(match.group(1))
                    for line in lines
                    if (match := _FOOTER_PATTERN.match(line))
                ),
                None,
            )
            row["source_pdf_page"] = page_number
            if footer_page is not None:
                row["source_section_page"] = footer_page

            if re.search(r"\bclosed\b|\bsealed\b", row_text, re.IGNORECASE):
                row["model_status"] = "closed_or_sealed"
                row["frequency_activations_per_year"] = None
                row["duration_hours_per_year"] = None
                row["volume_million_gallons_per_year"] = None
                continue

            cells = _read_annual_cells(row_lines, row)
            if len(cells) < 3:
                raise ValueError(f"Could not read three annual cells for {outfall_id}: {row_text}")
            last_cells = cells[:3]
            if all(re.fullmatch(r"\(\d+\)", cell) for cell in last_cells):
                row["model_status"] = "not_modeled_pending"
                row["frequency_activations_per_year"] = None
                row["duration_hours_per_year"] = None
                row["volume_million_gallons_per_year"] = None
                continue

            parsed_cells = [float(cell.strip("()").replace(",", "")) for cell in last_cells]
            row["model_status"] = "modeled"
            row["frequency_activations_per_year"] = parsed_cells[0]
            row["duration_hours_per_year"] = parsed_cells[1]
            row["volume_million_gallons_per_year"] = parsed_cells[2]

    # Refresh provenance counters from the extracted rows, not from the prior
    # snapshot, so a malformed source layout cannot silently keep old totals.
    statuses = [str(row.get("model_status")) for row in rows]
    model["metadata"]["outfall_record_count"] = len(rows)
    model["metadata"]["modeled_record_count"] = statuses.count("modeled")
    model["metadata"]["closed_or_sealed_record_count"] = statuses.count("closed_or_sealed")
    model["metadata"]["not_modeled_pending_record_count"] = statuses.count("not_modeled_pending")
    return model


def _refresh_from_pdf(pdf_path: str | Path, *, model_path: str | Path = MODEL_PATH) -> dict[str, Any]:
    """Rebuild the checked-in modeled table values from an official PDF copy."""
    source_path = Path(pdf_path)
    model = json.loads(Path(model_path).read_text(encoding="utf-8"))
    pdf_bytes = source_path.read_bytes()
    pdf_sha256 = hashlib.sha256(pdf_bytes).hexdigest()
    expected_sha256 = model["metadata"].get("source_pdf_sha256")
    if expected_sha256 and pdf_sha256 != expected_sha256:
        raise ValueError(
            f"PDF SHA-256 {pdf_sha256} differs from pinned 2018 source {expected_sha256}; "
            "inspect and curate a new source vintage instead of replacing this model"
        )
    try:
        completed = subprocess.run(
            [_PDF_TEXT_TOOL, "-raw", str(source_path), "-"],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
    except FileNotFoundError as error:
        raise RuntimeError("pdftotext (Poppler) is required for --refresh") from error
    model["metadata"]["source_pdf_sha256"] = pdf_sha256
    model["metadata"]["source_pdf_bytes"] = len(pdf_bytes)
    model = _parse_pdf_text(model, completed.stdout)
    return model


def _download_source_pdf() -> Path:
    """Download the pinned public source for an explicit refresh invocation."""
    import tempfile

    request = Request(
        str(_load_model()["metadata"]["source_url"]),
        headers={"User-Agent": "Lotline modeled-context source refresh/1.0"},
    )
    with urlopen(request, timeout=90) as response:
        payload = response.read()
    with tempfile.NamedTemporaryFile(prefix="alcosan-cwp-", suffix=".pdf", delete=False) as temporary:
        temporary.write(payload)
        temporary.flush()
        temporary_path = Path(temporary.name)
    return temporary_path


def _refresh_cli(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Rebuild the pinned ALCOSAN overflow model from its source PDF.")
    parser.add_argument("--refresh", action="store_true", help="extract the actual annual tables and update the JSON snapshot")
    parser.add_argument("--pdf", type=Path, help="cached source PDF; omitted means download the official URL")
    parser.add_argument("--output", type=Path, default=MODEL_PATH, help="output JSON path (default: checked-in model)")
    args = parser.parse_args(argv)
    if not args.refresh:
        parser.error("specify --refresh to rebuild the model")

    downloaded_path: Path | None = None
    try:
        pdf_path = args.pdf
        if pdf_path is None:
            downloaded_path = _download_source_pdf()
            pdf_path = downloaded_path
        model = _refresh_from_pdf(pdf_path)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(model, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        metadata = model["metadata"]
        print(
            f"Wrote {len(model['outfalls'])} rows ({metadata['modeled_record_count']} modeled, "
            f"{metadata['closed_or_sealed_record_count']} closed/sealed, "
            f"{metadata['not_modeled_pending_record_count']} pending); "
            f"source SHA-256 {metadata['source_pdf_sha256']}"
        )
        return 0
    except (OSError, subprocess.CalledProcessError, RuntimeError, ValueError) as error:
        parser.exit(2, f"overflow refresh failed: {error}\n")
    finally:
        if downloaded_path is not None:
            downloaded_path.unlink(missing_ok=True)


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


if __name__ == "__main__":
    raise SystemExit(_refresh_cli())
