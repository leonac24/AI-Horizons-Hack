import json

from core.config import ROOT, load_config
from core.engine import analyze
from core.environment_evidence import declared_overrides, parcel_environment_inputs
from core.metrics import Samples


def _parcel():
    parcels = json.loads((ROOT / "data/processed/parcels.json").read_text(encoding="utf-8"))["parcels"]
    return parcels["0070G00275000000"]


def test_real_parcel_carbon_uses_resolved_models_and_reports_partial_boundary():
    cfg = load_config()
    analysis = analyze(cfg, _parcel())
    for scenario in analysis.scenarios:
        carbon = scenario.metrics["carbon.per_household_horizon"]
        assert carbon.provenance != "placeholder"
        assert carbon.evidence["partial"] is True
        assert carbon.evidence["inputs"]["grid_kgco2e_by_year"]["years"]
        assert "grid_decarbonization_per_yr" not in carbon.evidence["inputs"]
        assert carbon.evidence["inputs"]["vmt_per_household_yr"]["source_ids"]
        assert abs(carbon.value - scenario.carbon.value[-1]) < .02
        assert set(carbon.sourceIds) <= set(cfg.sources.sources)
        assert carbon.evidence["inputs"]["embodied_kgco2e_psf"]["value"] != 45


def test_no_tract_or_sewershed_still_gets_disclosed_environment_estimates():
    inputs = parcel_environment_inputs({"id": "unlocated", "tract": None}, "midrise")
    for key in ("vmt_per_household_yr", "sewer_stress_index", "embodied_kgco2e_psf", "operational_kwh_psf_yr"):
        assert inputs[key]["value"] is not None
        assert inputs[key]["provenance"] != "observed"
        assert inputs[key]["limitations"]


def test_stale_placeholder_evidence_cannot_hide_a_sourced_model():
    inputs = parcel_environment_inputs({"evidence": {
        "embodied_kgco2e_psf": {"value": 45, "provenance": "placeholder"},
        "operational_kwh_psf_yr": {"value": None, "provenance": "observed"},
    }}, "small_multi")
    assert inputs["embodied_kgco2e_psf"]["value"] == 7.43
    assert inputs["operational_kwh_psf_yr"]["value"] == 8.95


def test_explicit_carbon_input_override_changes_the_served_total():
    cfg = load_config()
    parcel = _parcel()
    baseline = analyze(cfg, parcel).scenarios[0]
    changed = analyze(cfg, parcel, Samples(cfg, overrides={"operational_kwh_psf_yr": 0})).scenarios[0]
    metric = changed.metrics["carbon.per_household_horizon"]
    assert metric.value < baseline.metrics["carbon.per_household_horizon"].value
    assert metric.evidence["inputs"]["operational_kwh_psf_yr"]["value"] == 0
    assert metric.evidence["inputs"]["operational_kwh_psf_yr"]["provenance"] == "assumption"
    inputs = declared_overrides({"x": {"value": 1, "by_typology": {"midrise": {"value": 99}}}}, {"x": 4})
    assert "by_typology" not in inputs["x"]
