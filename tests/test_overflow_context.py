import json
from collections import Counter

from pipeline.overflow_context import (
    MODEL_PATH,
    PWSA_SOURCE_ID,
    _parse_pdf_text,
    build_overflow_inputs,
)


def _outfall(model, outfall_id):
    return next(row for row in model["outfalls"] if row["outfall_id"] == outfall_id)


def test_registry_keeps_source_references_and_spot_checked_pdf_values():
    model = json.loads(MODEL_PATH.read_text(encoding="utf-8"))
    assert model["metadata"]["outfall_record_count"] == 349
    assert model["metadata"]["modeled_record_count"] == 339
    assert Counter(row["source_table"] for row in model["outfalls"]) == {
        "4-4": 48, "4-5": 27, "4-8": 15, "4-9": 11,
        "4-12": 101, "4-13": 2, "4-14": 24, "4-15": 21,
        "4-18": 21, "4-19": 4, "4-22": 19, "4-23": 12,
        "4-26": 30, "4-27": 14,
    }

    high = _outfall(model, "A-42-OF")
    assert high["source_table"] == "4-22"
    assert high["source_pdf_page"] == high["source_section_page"] == 102
    assert (high["frequency_activations_per_year"], high["duration_hours_per_year"],
            high["volume_million_gallons_per_year"]) == (66, 1085, 777)
    assert high["model_vintage"] == 2018
    assert high["model_scenario"] == "existing_condition_typical_year"

    # The PDF's printed outfall row is physically on and numbered 4-36; do
    # not shift it to the following table continuation page.
    alias = _outfall(model, "C-04-02-OF2")
    assert alias["source_table"] == "4-4"
    assert alias["source_pdf_page"] == alias["source_section_page"] == 36

    restored = _outfall(model, "A1_MCD0002-3")
    assert restored["source_table"] == "4-5"
    assert restored["source_pdf_page"] == restored["source_section_page"] == 39
    assert (restored["frequency_activations_per_year"], restored["duration_hours_per_year"],
            restored["volume_million_gallons_per_year"]) == (15, 23, 0.209)

    zero = _outfall(model, "A-20Z-OF")
    assert zero["source_table"] == "4-12"
    assert zero["source_pdf_page"] == zero["source_section_page"] == 65
    assert (zero["frequency_activations_per_year"], zero["duration_hours_per_year"],
            zero["volume_million_gallons_per_year"]) == (0, 0, 0)

    pwsa = _outfall(model, "OF009E001")
    assert pwsa["source_table"] == "4-13"
    assert pwsa["source_pdf_page"] == pwsa["source_section_page"] == 69
    assert (pwsa["frequency_activations_per_year"], pwsa["duration_hours_per_year"],
            pwsa["volume_million_gallons_per_year"]) == (66, 657, 99.5)

    closed = _outfall(model, "A-66-OF")
    assert closed["model_status"] == "closed_or_sealed"
    assert closed["volume_million_gallons_per_year"] is None


def test_exact_composite_sewershed_matches_sum_named_outfall_volume_and_references():
    result = build_overflow_inputs({
        "id": "PARCEL-1",
        "combined_sewershed_ids": ["A-58/OF009E001"],
        "sewershed_join_method": "point inside county parcel polygon",
    })
    context = result["sewer_overflow_context"]
    assert context["value"] == 82 + 99.5
    assert context["unit"] == "million gallons/year"
    assert context["provenance"] == "modeled"
    assert context["evidence_tier"] == "direct_sewershed_outfall_match"
    assert [row["outfall_id"] for row in context["annual_volume_million_gallons_by_outfall"]] == [
        "A-58-OF", "OF009E001"
    ]
    assert [(row["source_table"], row["source_pdf_page"]) for row in
            context["annual_volume_million_gallons_by_outfall"]] == [("4-12", 66), ("4-13", 69)]
    assert context["source_ids"] == [
        "alcosan_cwp_section4_2018", "pwsa_combined_sewersheds"
    ]
    assert PWSA_SOURCE_ID == "pwsa_combined_sewersheds"
    assert context["model_scenario"] == "Existing-condition typical-year hydrologic and hydraulic model simulation"
    assert "not parcel wastewater flow or added-flow contribution" in context["limitations"]

    stress = result["sewer_stress_index"]
    assert stress["evidence_tier"] == "direct_sewershed_outfall_match"
    assert stress["normalization"]["reference_outfall_count"] == 339
    assert stress["value"] > 0
    assert "not a city or parcel-weighted mean" in stress["normalization"]["reference_scope"]


def test_unmatched_sheds_receive_disclosed_regional_fallback_not_nearest_outfall():
    result = build_overflow_inputs({
        "id": "PARCEL-2",
        "combined_sewershed_ids": ["PWSA-ABCDLMNO", "A-4", "C-05-00"],
    })
    context = result["sewer_overflow_context"]
    assert context["evidence_tier"] == "regional_modeled_fallback"
    assert context["value"] > 0
    assert context["low"] <= context["value"] <= context["high"]
    assert context["unmatched_sewershed_tokens"] == ["PWSA-ABCDLMNO", "A-4", "C-05-00"]
    assert context["annual_volume_million_gallons_by_outfall"] == []
    assert context["regional_fallback_method"]["outfall_count"] == 339
    assert context["regional_fallback_method"]["range_is_confidence_interval"] is False
    assert "Regional fallback used" in context["limitations"]
    assert "No nearest-outfall" in context["limitations"]
    assert result["sewer_stress_index"]["value"] == 1.0
    assert result["sewer_stress_index"]["evidence_tier"] == "regional_modeled_fallback"


def test_partial_match_uses_only_complete_exact_labels_and_discloses_missing_tokens():
    result = build_overflow_inputs({
        "combined_sewershed_ids": ["A-42", "A-42/NOT-A-REAL-OUTFALL"],
    })
    context = result["sewer_overflow_context"]
    assert context["evidence_tier"] == "direct_sewershed_outfall_match"
    assert context["value"] == 777
    assert context["unmatched_sewershed_tokens"] == ["NOT-A-REAL-OUTFALL"]
    assert "Some parcel sewershed labels or composite tokens were unmatched" in context["limitations"]


def test_restored_mcdonald_outfall_is_used_for_exact_parcel_context():
    result = build_overflow_inputs({"combined_sewershed_ids": ["A1_MCD0002-3"]})
    context = result["sewer_overflow_context"]
    assert context["evidence_tier"] == "direct_sewershed_outfall_match"
    assert context["value"] == 0.209
    assert context["annual_volume_million_gallons_by_outfall"][0]["outfall_id"] == "A1_MCD0002-3"


def test_model_loader_cache_key_changes_when_model_file_changes(tmp_path):
    model = json.loads(MODEL_PATH.read_text(encoding="utf-8"))
    first_value = _outfall(model, "A-42-OF")["volume_million_gallons_per_year"]
    path = tmp_path / "model.json"
    path.write_text(json.dumps(model), encoding="utf-8")
    initial = build_overflow_inputs({"combined_sewershed_ids": ["A-42"]}, model_path=path)
    assert initial["sewer_overflow_context"]["value"] == first_value

    _outfall(model, "A-42-OF")["volume_million_gallons_per_year"] = 9999
    path.write_text(json.dumps(model), encoding="utf-8")
    changed = build_overflow_inputs({"combined_sewershed_ids": ["A-42"]}, model_path=path)
    assert changed["sewer_overflow_context"]["value"] == 9999


def test_source_refresh_parser_reads_comma_cells_and_zero_rows():
    model = {
        "metadata": {"source_pdf_pages": 1},
        "outfalls": [
            {
                "outfall_id": "A-42-OF", "source_outfall_label": "A-42-OF",
                "source_table": "4-22", "model_status": "modeled",
            },
            {
                "outfall_id": "A-20Z-OF", "source_outfall_label": "A-20Z-OF",
                "source_table": "4-22", "model_status": "modeled",
            },
        ],
    }
    source_text = (
        "Table 4-22: Existing Condition, Typical Year Annual CSO Discharge Summary\n"
        "CSO Outfall Owner Frequency Duration Volume\n"
        "A-42-OF ALCOSAN 66 1,085 777\n"
        "A-20Z-OF ALCOSAN 0 0 0\n"
        "4 - 102\n"
    )

    refreshed = _parse_pdf_text(model, source_text)
    by_id = {row["outfall_id"]: row for row in refreshed["outfalls"]}
    assert (
        by_id["A-42-OF"]["frequency_activations_per_year"],
        by_id["A-42-OF"]["duration_hours_per_year"],
        by_id["A-42-OF"]["volume_million_gallons_per_year"],
    ) == (66, 1085, 777)
    assert (
        by_id["A-20Z-OF"]["frequency_activations_per_year"],
        by_id["A-20Z-OF"]["duration_hours_per_year"],
        by_id["A-20Z-OF"]["volume_million_gallons_per_year"],
    ) == (0, 0, 0)
