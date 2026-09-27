"""Evidence boundaries for the new tract and site context."""

import pytest

from core.engine import analyze
from pipeline.build_parcels import _choose_location, _null_reported_assessment_zeros, _points
from pipeline.enrich_context import (
    _polygon_matches,
    _renter_income_values,
    _tract_values,
    _valid_single_parcel_sales,
    _write_parcel_evidence,
)


def test_acs_burden_excludes_not_computed_and_keeps_income_moe():
    income = {"42003020300": {"B19013_E001": "72000", "B19013_M001": "4100"}}
    burden = {
        "42003020300": {
            "B25070_E001": "100",
            "B25070_E011": "20",
            "B25070_E007": "10",
            "B25070_E008": "10",
            "B25070_E009": "10",
            "B25070_E010": "10",
            **{f"B25070_M{k:03d}": "2" for k in (1, 7, 8, 9, 10, 11)},
        }
    }
    row = _tract_values(income, burden)["42003020300"]
    assert row["tract_median_household_income"] == 72000
    assert row["tract_median_household_income_moe"] == 4100
    assert row["tract_renter_cost_burden_share"] == 0.5  # 40 / (100 - 20)
    assert row["tract_renter_cost_burden_low"] < 0.5 < row["tract_renter_cost_burden_high"]


def test_missing_or_suppressed_acs_values_do_not_become_zero():
    rows = _tract_values(
        {"42003020300": {"B19013_E001": "-666666666", "B19013_M001": "-222222222"}},
        {"42003020300": {"B25070_E001": "0", "B25070_E011": "0"}},
    )
    assert rows["42003020300"] == {}


def test_joined_tract_values_replace_placeholders_without_claiming_sewer_stress(cfg, lot):
    real = {
        **lot,
        "tract": "42003020300",
        "tract_median_household_income": 72000,
        "tract_median_household_income_moe": 4100,
        "tract_renter_cost_burden_share": 0.5,
        "tract_renter_cost_burden_low": 0.4,
        "tract_renter_cost_burden_high": 0.6,
        "fema_flood_zones": ["AE"],
        "fema_sfha": True,
        "fema_join_method": "parcel polygon area overlap",
        "combined_sewershed_ids": ["O-25"],
        "sewershed_join_method": "parcel polygon area overlap",
    }
    result = analyze(cfg, real)
    metrics = {m.id: m for m in result.site_context}
    facts = {f.id: f for f in result.site_facts}
    assert metrics["site.tract_median_income"].value == 72000
    assert metrics["site.tract_median_income"].provenance == "observed"
    assert metrics["site.renter_cost_burden"].value == 50
    assert metrics["site.renter_cost_burden"].provenance == "modeled"
    assert facts["site.fema_flood"].provenance == "observed"
    assert "AE" in facts["site.fema_flood"].value
    assert facts["site.combined_sewershed"].value == "O-25"
    assert metrics["site.sewer_stress"].provenance == "placeholder"


def test_unmatched_flood_is_unknown_not_safe(cfg, lot):
    facts = {f.id: f for f in analyze(cfg, lot).site_facts}
    assert facts["site.fema_flood"].provenance == "placeholder"
    assert "No mapped zone match" in facts["site.fema_flood"].value


def test_polygon_interior_point_and_centroid_fallback_use_distinct_methods():
    gpd = pytest.importorskip("geopandas")
    from shapely.geometry import box, mapping

    records = [
        {"id": "WITH_BOUNDARY", "lon": -1, "lat": -1},
        {"id": "NO_BOUNDARY", "lon": 0.5, "lat": 0.5},
    ]
    boundaries = {"WITH_BOUNDARY": {"geometry": mapping(box(0, 0, 1, 1))}}
    layer = gpd.GeoDataFrame({"zone": ["AE"], "geometry": [box(0, 0, 1, 1)]}, crs=4326)
    hits = _polygon_matches(records, boundaries, layer, "zone")
    assert hits["WITH_BOUNDARY"][0]["value"] == "AE"
    assert hits["WITH_BOUNDARY"][0]["join_method"] == "point inside county parcel polygon"
    assert (
        hits["NO_BOUNDARY"][0]["join_method"] == "published parcel centroid (boundary unavailable)"
    )


def test_location_fallback_order_preserves_unlocated_pin():
    from shapely.geometry import box, mapping

    polygon = {"geometry": mapping(box(-80, 40, -79, 41))}
    point = _choose_location(-70, 30, polygon, (-79.5, 40.5))
    assert point[2] == "county parcel polygon interior point"
    centroid = _choose_location(-79.9, 40.4, None, (-79.5, 40.5))
    assert centroid == (-79.9, 40.4, "published parcel centroid")
    address = _choose_location(None, None, None, (-79.5, 40.5))
    assert address == (-79.5, 40.5, "PIN-matched county address point (approximate)")
    assert _choose_location(None, None) == (None, None, None)


def test_unlocated_parcel_is_excluded_from_geojson_points_not_index_records():
    records = [
        {
            "id": "LOCATED",
            "lon": -80,
            "lat": 40,
            "address": "A",
            "lot_area_sf": 1,
            "zoning": None,
            "neighborhood": None,
            "public": False,
        },
        {
            "id": "UNLOCATED",
            "lon": None,
            "lat": None,
            "address": "B",
            "lot_area_sf": 2,
            "zoning": None,
            "neighborhood": None,
            "public": False,
        },
    ]
    geojson = _points(records, [])
    assert len(records) == 2
    assert [feature["properties"]["id"] for feature in geojson["features"]] == ["LOCATED"]


def test_unusable_county_zero_assessment_values_stay_null_with_source_flags():
    pd = pytest.importorskip("pandas")
    rows = _null_reported_assessment_zeros(
        pd.DataFrame(
            [
                {"lot_area_sf": 0, "land_value_usd": 0},
                {"lot_area_sf": 1200, "land_value_usd": 3000},
            ]
        )
    )
    assert pd.isna(rows.iloc[0]["lot_area_sf"])
    assert pd.isna(rows.iloc[0]["land_value_usd"])
    assert rows.iloc[0]["assessment_zero_fields"] == ["lot_area_sf", "land_value_usd"]
    assert rows.iloc[1]["lot_area_sf"] == 1200
    assert rows.iloc[1]["assessment_zero_fields"] == []


def test_acs_b25118_renter_bins_keep_counts_and_moes_without_zero_filling():
    row = {"B25118_E014": "100", "B25118_M014": "20"}
    row.update({f"B25118_E{i:03d}": "5" for i in range(15, 26)})
    row.update({f"B25118_M{i:03d}": "2" for i in range(15, 26)})
    bins = _renter_income_values({"42003020300": row})["42003020300"]
    assert bins["total_renter_households"] == 100
    assert len(bins["bins"]) == 11
    assert bins["bins"][0] == {
        "lower_usd": 0,
        "upper_usd": 5000,
        "label": "less than $5,000",
        "households": 5,
        "moe_90": 2,
    }
    row["B25118_E020"] = "-666666666"
    assert _renter_income_values({"42003020300": row}) == {}


def test_valid_sales_exclude_nonvalid_bundled_and_unmatched_records():
    rows = [
        {
            "PARID": "PIN1",
            "SALEDATE": "01/02/2024",
            "PRICE": "50000",
            "DEEDBOOK": "D1",
            "DEEDPAGE": "1",
            "SALEDESC": "Valid Sale",
        },
        {
            "PARID": "PIN2",
            "SALEDATE": "01/02/2024",
            "PRICE": "70000",
            "DEEDBOOK": "D2",
            "DEEDPAGE": "2",
            "SALEDESC": "Valid Sale",
        },
        {
            "PARID": "PIN3",
            "SALEDATE": "01/02/2024",
            "PRICE": "70000",
            "DEEDBOOK": "D2",
            "DEEDPAGE": "2",
            "SALEDESC": "Valid Sale",
        },
        {
            "PARID": "PIN4",
            "SALEDATE": "01/02/2024",
            "PRICE": "90000",
            "DEEDBOOK": "D4",
            "DEEDPAGE": "4",
            "SALEDESC": "Invalid",
        },
    ]
    parcels = [
        {"id": f"PIN{i}", "lot_area_sf": 1000, "land_use": "VACANT LAND"} for i in range(1, 5)
    ]
    sales = _valid_single_parcel_sales(rows, parcels, "sales", "snapshot")
    assert len(sales) == 1
    assert sales[0] == {
        "parcel_id": "PIN1",
        "sale_price": 50000.0,
        "sale_date": "2024-02-01",
        "parcel_area_sqft": 1000,
        "arm_length": True,
        "vacant": True,
        "source_id": "sales",
        "snapshot_id": "snapshot",
        "geography": "parcel",
        "neighborhood": None,
        "zoning": None,
        "lon": None,
        "lat": None,
        "context_as_of": "current parcel record; not sale-date condition or zoning",
    }


def test_evidence_artifact_keeps_compact_pin_row_and_explicit_source_provenance(
    tmp_path, monkeypatch
):
    import json

    import pipeline.enrich_context as context

    monkeypatch.setattr(context, "PROCESSED", tmp_path)
    record = {
        "id": "PIN1",
        "location_method": None,
        "acs_renter_income_geography": {"type": "county", "geoid": "42003"},
        "acs_renter_income_bins": {
            "total_renter_households": 10,
            "total_moe_90": 2,
            "bins": [{"lower_usd": 0, "upper_usd": 5000, "households": 10, "moe_90": 2}],
        },
        "assessment_zero_fields": ["lot_area_sf"],
    }
    _write_parcel_evidence(
        [record], [], {"acs_2024_b25118": "acs-hash", "wprdc_assessments": "assessment-hash"}, {}
    )
    row = json.loads((tmp_path / "parcel_evidence.jsonl").read_text(encoding="utf-8"))
    assert row["id"] == "PIN1" and row["parcel"] == {}
    assert row["evidence"]["acs_renter_income_bins"]["provenance"] == "modeled"
    assert row["evidence"]["acs_renter_income_bins"]["geography"] == {
        "type": "county",
        "geoid": "42003",
    }
    assert row["evidence"]["county_assessment_zero_fields"]["value"] == {"lot_area_sf": 0}
    manifest = json.loads((tmp_path / "parcel_evidence_manifest.json").read_text(encoding="utf-8"))
    assert manifest["source_manifest_hash"]
