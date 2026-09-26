"""Evidence boundaries for the new tract and site context."""

import pytest

from core.engine import analyze
from pipeline.enrich_context import _polygon_matches, _tract_values


def test_acs_burden_excludes_not_computed_and_keeps_income_moe():
    income = {"42003020300": {"B19013_E001": "72000", "B19013_M001": "4100"}}
    burden = {"42003020300": {
        "B25070_E001": "100", "B25070_E011": "20",
        "B25070_E007": "10", "B25070_E008": "10",
        "B25070_E009": "10", "B25070_E010": "10",
        **{f"B25070_M{k:03d}": "2" for k in (1, 7, 8, 9, 10, 11)},
    }}
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
        **lot, "tract": "42003020300", "tract_median_household_income": 72000,
        "tract_median_household_income_moe": 4100,
        "tract_renter_cost_burden_share": 0.5,
        "tract_renter_cost_burden_low": 0.4, "tract_renter_cost_burden_high": 0.6,
        "fema_flood_zones": ["AE"], "fema_sfha": True,
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
    assert hits["NO_BOUNDARY"][0]["join_method"] == "published parcel centroid (boundary unavailable)"
