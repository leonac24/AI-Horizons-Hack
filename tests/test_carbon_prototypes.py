import json
import os
import statistics
from pathlib import Path

import pytest

from pipeline import carbon_prototypes
from pipeline.carbon_prototypes import build_prototype_evidence, build_prototype_inputs

ROOT = Path(__file__).resolve().parents[1]
DATA_PATH = ROOT / "data" / "models" / "carbon_prototypes.json"
ENERGY_PATH = ROOT / "data" / "models" / "carbon_prototypes" / "doe_energy_outputs.json"
SOURCES_PATH = ROOT / "data" / "models" / "carbon_prototypes" / "sources.json"
EXPECTED_TYPOLOGIES = {
    "detached", "adu_pair", "two_unit", "rowhouse", "small_multi", "midrise",
}


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_all_typologies_get_sourced_envelopes_and_named_proxies():
    model = _json(DATA_PATH)
    assert set(model["by_typology"]) == EXPECTED_TYPOLOGIES
    for typology_id in EXPECTED_TYPOLOGIES:
        inputs = build_prototype_inputs(typology_id)
        assert inputs["proxy_label"]
        for key, unit in (
            ("embodied_kgco2e_psf", "kgCO2e/sf"),
            ("operational_kwh_psf_yr", "kWh/sf/yr"),
        ):
            envelope = inputs[key]
            assert envelope["unit"] == unit
            assert envelope["provenance"] == "modeled"
            assert envelope["source_ids"]
            assert envelope["source_urls"]
            assert envelope["low"] <= envelope["value"] <= envelope["high"]
            assert all(envelope[field] >= 0 for field in ("low", "value", "high"))


def test_energy_values_are_calculated_from_doe_meter_and_conditioned_area():
    extracted = _json(ENERGY_PATH)
    assert extracted["source_id"] == "doe_iecc2021_residential_cz5a_outputs"
    for prototype, typologies in {
        "sf_detached": {"detached", "adu_pair", "two_unit", "rowhouse"},
        "mf_lowrise": {"small_multi", "midrise"},
    }.items():
        rows = [row for row in extracted["rows"] if row["prototype"] == prototype]
        assert len(rows) == 4
        assert {row["foundation"] for row in rows} == {
            "slab", "crawlspace", "heatedbsmt", "unheatedbsmt",
        }
        values = [row["electricity_facility_meter_kwh_yr"] / row["conditioned_area_sf"] for row in rows]
        for row, value in zip(rows, values):
            assert row["electricity_kwh_per_conditioned_sf_yr"] == pytest.approx(value, abs=1e-7)
            fuels = row["fuel_end_uses_kbtu_yr"]
            assert fuels["Electricity"] > 0
            assert all(amount == 0 for fuel, amount in fuels.items() if fuel != "Electricity")
        for typology_id in typologies:
            energy = build_prototype_inputs(typology_id)["operational_kwh_psf_yr"]
            adjustment = energy["proxy_adjustment"]
            assert energy["value"] == pytest.approx(statistics.mean(values), abs=0.01)
            assert energy["low"] == pytest.approx(min(values) * adjustment["low_factor"], abs=0.01)
            assert energy["high"] == pytest.approx(max(values) * adjustment["high_factor"], abs=0.01)
            assert energy["prototype_proxy"] == prototype


def test_embodied_center_scope_and_multifamily_proxy_adjustment_are_explicit():
    sources = _json(SOURCES_PATH)["sources"]
    source = next(item for item in sources if item["id"] == "jungclaus_2024_sf_embodied_a1a3")
    assert "A1-A3" in source["scope"]
    assert "39 to 121 kgCO₂e/m²" in source["source_extract"]
    assert "storage" in source["biogenic_carbon"]
    assert "midpoint" in build_prototype_inputs("detached")["embodied_kgco2e_psf"]["center_basis"]

    direct = build_prototype_inputs("detached")["embodied_kgco2e_psf"]
    multifamily = build_prototype_inputs("small_multi")["embodied_kgco2e_psf"]
    midrise = build_prototype_inputs("midrise")["embodied_kgco2e_psf"]
    assert direct["low"] == 3.62 and direct["high"] == 11.24
    assert multifamily["low"] == 1.81 and multifamily["high"] == 22.48
    assert multifamily["proxy_adjustment"]["provenance"] == "assumption"
    assert midrise["proxy_adjustment"]["high_factor"] == 2.0
    assert "not a confidence interval" in direct["limitations"]


def test_nonnative_energy_forms_widen_ranges_but_keep_native_center():
    for typology_id, expected in {
        "adu_pair": (5.33, 12.72),
        "two_unit": (5.33, 12.72),
        "rowhouse": (5.33, 12.72),
        "midrise": (6.09, 13.95),
    }.items():
        energy = build_prototype_inputs(typology_id)["operational_kwh_psf_yr"]
        assert (energy["low"], energy["high"]) == expected
        assert energy["proxy_adjustment"]["provenance"] == "assumption"
        assert energy["value"] == (8.07 if typology_id != "midrise" else 8.95)

    for typology_id in ("detached", "small_multi"):
        energy = build_prototype_inputs(typology_id)["operational_kwh_psf_yr"]
        assert energy["proxy_adjustment"]["provenance"] == "none"


def test_model_json_regenerates_deterministically_from_checked_in_sources(tmp_path):
    generated = carbon_prototypes.build_prototype_model()
    assert generated == _json(DATA_PATH)
    output = tmp_path / "carbon_prototypes.json"
    assert carbon_prototypes.write_prototype_model(output) == generated
    assert output.read_bytes() == DATA_PATH.read_bytes()


def test_evidence_envelopes_expose_by_typology_and_are_detached_copies():
    evidence = build_prototype_evidence()
    for field in ("embodied_kgco2e_psf", "operational_kwh_psf_yr"):
        assert set(evidence[field]["by_typology"]) == EXPECTED_TYPOLOGIES
    evidence["embodied_kgco2e_psf"]["by_typology"]["detached"]["value"] = -1
    assert build_prototype_evidence()["embodied_kgco2e_psf"]["by_typology"]["detached"]["value"] == 7.43


def test_model_cache_refreshes_when_file_size_or_mtime_changes(tmp_path, monkeypatch):
    path = tmp_path / "carbon_prototypes.json"
    monkeypatch.setattr(carbon_prototypes, "MODEL_PATH", path)
    carbon_prototypes._load_model_cached.cache_clear()
    path.write_text('{"schema_version":1,"by_typology":{"first":1}}', encoding="utf-8")
    assert set(carbon_prototypes._load_model()["by_typology"]) == {"first"}
    previous_mtime_ns = path.stat().st_mtime_ns
    path.write_text('{"schema_version":1,"by_typology":{"other":1}}', encoding="utf-8")
    assert path.stat().st_size == len('{"schema_version":1,"by_typology":{"first":1}}')
    os.utime(path, ns=(previous_mtime_ns + 1_000_000, previous_mtime_ns + 1_000_000))
    assert set(carbon_prototypes._load_model()["by_typology"]) == {"other"}


def test_unknown_typology_is_not_silently_filled():
    with pytest.raises(KeyError, match="unknown housing typology"):
        build_prototype_inputs("unknown")
