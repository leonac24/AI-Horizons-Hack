from typing import ClassVar

from core.environment_model import environment_defaults_from_config, estimate_environment
from pipeline.environment_inputs import (
    build_annual_grid_path,
    build_latch_tract_index,
    embodied_carbon_from_schedule,
    latch_envelope_for_parcel,
    normalize_tract_geoid,
    read_latch_tract_vmt,
)


def test_latch_annualization_requires_explicit_weekend_factor():
    rows = [{"GEOID": "42003480200", "VMT": "30.0", "SUPPRESSED": "false"}]
    weekday = read_latch_tract_vmt(
        rows, "42003480200", tract_field="GEOID", weekday_vmt_field="VMT",
        profile="all households", suppressed_field="SUPPRESSED",
    )
    assert weekday["value"] == 30
    assert weekday["unit"] == "vehicle miles/household/weekday"
    assert "annualization" not in weekday
    annual = read_latch_tract_vmt(
        rows, "42003480200", tract_field="GEOID", weekday_vmt_field="VMT",
        profile="all households", weekday_days_per_year=260,
        weekend_to_weekday_ratio=0.65, suppressed_field="SUPPRESSED",
    )
    assert annual["value"] == 30 * (260 + 105 * 0.65)
    assert annual["geography"] == "2010 tract 42003480200"


def test_latch_suppression_and_geoids_are_preserved():
    assert normalize_tract_geoid("42003-4802.00") == "42003480200"
    result = read_latch_tract_vmt(
        [{"GEOID": "42003480200", "VMT": "-", "FLAG": "suppressed"}],
        "42003480200", tract_field="GEOID", weekday_vmt_field="VMT",
        profile="profile 3", suppressed_field="FLAG",
    )
    assert result["value"] is None
    assert result["evidence_tier"] == "unresolved_source_value"


def test_environment_scenario_scales_components_and_keeps_capacity_unknown():
    defaults = {
        "analysis_years": 2,
        "embodied_kgco2e_psf": {"value": 10, "low": 8, "high": 12,
                                  "by_typology": {"rowhouse": {"value": 10, "low": 8, "high": 12}}},
        "operational_kwh_psf_yr": {"value": 2, "low": 1, "high": 3},
        "vmt_per_household_yr": {"value": 100, "low": 80, "high": 120},
        "grid_kgco2e_per_kwh": {"value": 0.5, "low": 0.4, "high": 0.6},
        "grid_decarbonization_per_yr": {"value": 0.1, "low": 0.0, "high": 0.2},
        "kgco2e_per_vmt": {"value": 0.2, "low": 0.2, "high": 0.2},
        "wastewater_gpd_per_home": {"value": 150, "low": 100, "high": 200},
    }
    for key, envelope in defaults.items():
        if isinstance(envelope, dict):
            envelope["source_ids"] = [f"test:{key}"]
            envelope["provenance"] = "assumption"
    outputs = estimate_environment(
        {"sewershed_id": "S-17"}, "rowhouse", 3, 1000,
        {"sewer_overflow_context": {"value": 12, "low": 8, "high": 16,
                                    "unit": "historical overflow events", "source_ids": ["alcosan_report"]}},
        defaults,
    )
    assert outputs["embodied_kgco2e_scenario"]["value"] == 30000
    assert outputs["operational_kwh_scenario_yr"]["value"] == 6000
    assert outputs["wastewater_added_gpd"]["value"] == 450
    assert outputs["wastewater_added_gpd"]["confirmation_needed"].startswith("PWSA")
    assert outputs["sewer_capacity"]["value"] is None
    assert "does not measure parcel-specific" in outputs["sewer_overflow_context"]["limitations"]
    assert outputs["carbon_scenario"]["value"] == 10000 + (2000 * .5 + 100 * .2) + (2000 * .45 + 100 * .2)
    assert outputs["carbon_scenario"]["partial"] is True
    assert outputs["carbon_scenario"]["carbon_series"]["years"] == [0, 1, 2]
    assert outputs["carbon_scenario"]["carbon_series"]["value"][0] == 10000
    assert outputs["carbon_scenario"]["carbon_series"]["low"][0] == 8000
    assert outputs["carbon_scenario"]["carbon_series"]["high"][0] == 12000


def test_missing_scenario_data_is_not_zero_filled():
    outputs = estimate_environment({}, "detached", 1, 1000, {}, {})
    assert outputs["carbon_scenario"]["value"] is None
    assert outputs["wastewater_added_gpd"] is None
    assert outputs["sewer_capacity"]["value"] is None


def test_annual_grid_ingestion_selects_only_named_series_and_keeps_horizon():
    rows = [
        {"region": "RFCW", "case": "mid", "year": "2030", "rate": "500"},
        {"region": "RFCW", "case": "mid", "year": "2040", "rate": "400"},
        {"region": "RFCW", "case": "high", "year": "2030", "rate": "900"},
    ]
    path = build_annual_grid_path(
        rows, region="RFCW", scenario="mid", year_field="year", region_field="region",
        scenario_field="case", emissions_field="rate", unit="kg/MWh",
    )
    assert path["years"] == [2030, 2040]
    assert path["value"] == [0.5, 0.4]
    assert path["series"] == "average"
    assert "no extrapolation" in path["limitations"]


def test_embodied_material_schedule_reports_stage_totals_and_missing_factors():
    rows = embodied_carbon_from_schedule(
        [{"material": "concrete", "quantity_per_sf": "0.2"},
         {"material": "steel", "quantity_per_sf": "0.01"}],
        [{"material": "concrete", "stage": "A1-A3", "kgco2e_per_unit": "300",
          "low": "250", "high": "350", "source_id": "epd-concrete"}],
        typology_id="midrise",
    )
    assert rows["value"] is None
    assert rows["partial_value_kgco2e_sf"] == 60
    assert rows["stage_totals_kgco2e_sf"]["A1-A3"]["value"] == 60
    assert rows["complete"] is False
    assert rows["missing_materials"] == ["steel"]


def test_environment_uses_year_labeled_grid_path_and_discloses_terminal_hold():
    defaults = {
        "analysis_years": 3, "analysis_start_year": 2026,
        "embodied_kgco2e_psf": {"value": 1, "low": 1, "high": 1, "source_ids": ["test:materials"], "provenance": "assumption"},
        "operational_kwh_psf_yr": {"value": 1, "low": 1, "high": 1, "source_ids": ["test:energy"], "provenance": "assumption"},
        "vmt_per_household_yr": {"value": 0, "low": 0, "high": 0, "source_ids": ["test:travel"], "provenance": "assumption"},
        "kgco2e_per_vmt": {"value": 0.2, "low": 0.2, "high": 0.2, "source_ids": ["test:vehicle"], "provenance": "assumption"},
    }
    evidence = {"grid_kgco2e_by_year": {
        "value": [0.5, 0.4], "low": [0.5, 0.4], "high": [0.5, 0.4],
        "years": [2026, 2027], "source_ids": ["nrel_cambium"],
    }}
    result = estimate_environment({}, "detached", 1, 1000, evidence, defaults)["carbon_scenario"]
    assert result["value"] == 2300  # 1000 upfront + 500 + 400 + terminal-year hold at 400
    assert result["grid_path_extrapolation"] == "terminal_year_hold"
    assert "hold the last modeled rate constant" in result["limitations"]


def test_latch_citywide_index_joins_by_2010_tract_and_keeps_unmatched_null():
    index = build_latch_tract_index(
        [{"tract": "42003480200", "weekday": "20", "flag": "false"}],
        tract_field="tract", weekday_vmt_field="weekday", profile="all households",
        suppressed_field="flag",
    )
    assert latch_envelope_for_parcel({"tract_2010": "42003-4802.00"}, index)["value"] == 20
    assert latch_envelope_for_parcel({"id": "x"}, index)["value"] is None


def test_config_defaults_only_include_cited_non_placeholder_inputs():
    class FakeConfig:
        sources = type("Sources", (), {"sources": {"epa_egrid": {}, "uncited": {}}})()
        data: ClassVar[dict] = {
            "grid_kgco2e_per_kwh": type("A", (), {
                "source": "epa_egrid", "provenance": "assumption", "unit": "kg/kWh",
                "rationale": "EPA grid rate", "value": 0.4, "low": 0.3, "high": 0.5,
                "for_typology": lambda self, _typ: self,
            })(),
            "vmt_per_household_yr": type("A", (), {
                "source": None, "provenance": "placeholder", "unit": "miles/yr",
                "rationale": "no source", "value": 10, "low": 5, "high": 20,
                "for_typology": lambda self, _typ: self,
            })(),
        }
        def assumption(self, key):
            if key == "analysis_years":
                return type("Years", (), {"value": 60})()
            return self.data[key]

    defaults = environment_defaults_from_config(FakeConfig(), "detached")
    assert "grid_kgco2e_per_kwh" in defaults
    assert "vmt_per_household_yr" not in defaults
    assert defaults["analysis_years"] == 60


def test_weekday_vmt_is_never_treated_as_annual_travel():
    evidence = {"vmt_per_household_yr": {
        "value": 25, "low": 25, "high": 25,
        "unit": "vehicle miles/household/weekday", "provenance": "modeled",
        "source_ids": ["bts_latch_2017"],
    }}
    outputs = estimate_environment({}, "detached", 1, 1000, evidence, {})
    assert outputs["vmt_scenario_yr"] is None
    assert outputs["carbon_scenario"]["value"] is None


def test_pa_dep_flow_reference_times_declared_occupancy_range():
    class FakeConfig:
        sources = type("Sources", (), {"sources": {
            "dep_manual_configured_in_yaml": type("Source", (), {"name": "Domestic Wastewater Facilities Manual"})(),
        }})()
        def assumption(self, key):
            if key == "analysis_years":
                return type("Years", (), {"value": 60})()
            raise KeyError(key)

    defaults = environment_defaults_from_config(FakeConfig(), "detached")
    outputs = estimate_environment({}, "detached", 1, 1000, {}, defaults)
    flow = outputs["wastewater_added_gpd"]
    assert flow["value"] == 200
    assert flow["low"] == 100
    assert flow["high"] == 400
    assert flow["source_ids"] == ["dep_manual_configured_in_yaml"]
    assert "not a measured discharge" in flow["limitations"]
    assert outputs["sewer_capacity"]["value"] is None
    assert outputs["wastewater_occupants_per_home"]["value"] == 2
