from __future__ import annotations

import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from pipeline import carbon_geography


class CarbonGeographyTests(unittest.TestCase):
    def test_direct_tract_vmt_is_annualized_and_vintage_caveat_is_explicit(self) -> None:
        result = carbon_geography.build_geographic_inputs({"tract": "42003020300"})
        vmt = result["vmt_per_household_yr"]

        self.assertEqual(vmt["geography"]["type"], "tract")
        self.assertEqual(vmt["geography"]["geoid"], "42003020300")
        self.assertIn("exact-code proxy", vmt["geography"]["vintage"])
        self.assertEqual(vmt["fallback_level"], None)
        self.assertAlmostEqual(
            vmt["value"],
            vmt["weekday_value_miles_per_household_day"]
            * vmt["annualization"]["equivalent_days_per_year"]["central"],
            places=2,
        )
        self.assertTrue(any("does not verify" in item for item in vmt["limitations"]))
        self.assertIn("fhwa_nhts_2017_annualization", vmt["source_ids"])

    def test_missing_tract_uses_household_weighted_county_fallback(self) -> None:
        vmt = carbon_geography.build_geographic_inputs({"tract": "42003000000"})[
            "vmt_per_household_yr"
        ]

        self.assertEqual(vmt["fallback_level"], "county")
        self.assertEqual(vmt["geography"]["type"], "county")
        self.assertEqual(vmt["geography"]["geoid"], "42003")
        self.assertAlmostEqual(vmt["weekday_value_miles_per_household_day"], 33.019997)
        self.assertTrue(any("household-count-weighted" in item for item in vmt["limitations"]))

    def test_absent_geography_uses_visible_pittsburgh_project_fallback(self) -> None:
        inputs = carbon_geography.build_geographic_inputs({})
        vmt = inputs["vmt_per_household_yr"]

        self.assertEqual(vmt["geography"]["geoid"], "42003")
        self.assertTrue(any("no tract or county identifier" in item for item in vmt["limitations"]))
        self.assertEqual(inputs["grid_kgco2e_per_kwh"]["geography"]["id"], "PJM_East")

    def test_state_only_input_uses_state_estimate_and_region_proxy(self) -> None:
        inputs = carbon_geography.build_geographic_inputs({"state": "PA"})

        self.assertEqual(inputs["vmt_per_household_yr"]["fallback_level"], "state")
        self.assertEqual(inputs["vmt_per_household_yr"]["geography"]["fips"], "42")
        self.assertEqual(inputs["grid_kgco2e_per_kwh"]["geography"]["id"], "PJM_East")
        self.assertTrue(any("state proxy" in item for item in inputs["grid_kgco2e_by_year"]["limitations"]))

    def test_cambium_path_has_annual_interpolation_scenario_spread_and_terminal_hold(self) -> None:
        inputs = carbon_geography.build_geographic_inputs({"county_fips": "42003"})
        grid = inputs["grid_kgco2e_by_year"]
        scalar = inputs["grid_kgco2e_per_kwh"]
        decarb = inputs["grid_decarbonization_per_yr"]

        self.assertEqual(grid["years"], list(range(2025, 2051)))
        self.assertEqual(scalar["geography"]["id"], "PJM_East")
        self.assertAlmostEqual(scalar["value"], 0.4031924)
        self.assertAlmostEqual(grid["value"][0], 0.4031924)
        self.assertAlmostEqual(grid["value"][5], 0.32292905)
        expected_2027 = 0.4031924 + (0.32292905 - 0.4031924) * 2 / 5
        self.assertAlmostEqual(grid["value"][2], expected_2027)
        self.assertLessEqual(grid["low"][2], grid["value"][2])
        self.assertGreaterEqual(grid["high"][2], grid["value"][2])
        self.assertEqual(grid["extrapolation"]["method"], "terminal_year_hold")
        self.assertEqual(len(grid["extrapolation"]["alternative_scenario_terminal_values"]), 8)
        self.assertAlmostEqual(decarb["value"], 0.029003789, places=8)
        self.assertAlmostEqual(scalar["historical_reference"]["value"], 0.41551510490798)
        self.assertEqual(scalar["historical_reference"]["source_id"], "epa_egrid_2023_reference")
        self.assertIn("not AER generation", grid["rate_basis"])
        self.assertTrue(grid["distribution_loss_adjustment_included"])
        self.assertIn("end-use-demand basis", " ".join(grid["limitations"]))

    def test_model_loader_reloads_when_file_revision_changes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "model.json"
            path.write_text('{"revision":1}', encoding="utf-8")
            original_cache = carbon_geography._MODEL_CACHE.copy()
            carbon_geography._MODEL_CACHE.clear()
            try:
                with mock.patch.object(carbon_geography, "MODEL_PATH", path):
                    self.assertEqual(carbon_geography._load_model()["revision"], 1)
                    path.write_text('{"revision":2,"changed_size":true}', encoding="utf-8")
                    self.assertEqual(carbon_geography._load_model()["revision"], 2)
            finally:
                carbon_geography._MODEL_CACHE.clear()
                carbon_geography._MODEL_CACHE.update(original_cache)

    def test_offline_refresh_parses_local_latch_csv_and_cambium_workbook(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            latch = temp / "latch.csv"
            latch.write_text(
                "geocode,est_vmiles,hh_cnt,flag_acs_lt_moe,flag_manhattan_trt,flag_gpqtr,flag_incomplete_acs\n"
                "42003000001,10,100,0,0,0,0\n"
                "42003000002,20,300,1,0,0,0\n",
                encoding="utf-8",
            )
            parcels = temp / "parcels.json"
            parcels.write_text(json.dumps({"parcels": {
                "one": {"tract": "42003000001"},
                "two": {"tract": "42003000099"},
                "three": {},
            }}), encoding="utf-8")
            workbook = temp / "cambium.xlsx"
            _write_cambium_fixture(workbook)
            output = temp / "model.json"

            refresh = carbon_geography.refresh_model_data(
                latch_csv_path=latch,
                cambium_xlsx_path=workbook,
                parcels_json_path=parcels,
                output_path=output,
            )
            model = json.loads(output.read_text(encoding="utf-8"))

            self.assertEqual(refresh["latch_direct_tracts"], 1)
            self.assertEqual(refresh["cambium_regions"], 1)
            self.assertEqual(model["latch"]["county_weekday_vmt"]["42003"]["avg_weekday_household_vmiles"], 17.5)
            self.assertEqual(model["cambium"]["county_to_region"]["42003"]["gea_region"], "PJM_East")
            self.assertEqual(model["cambium"]["regions"]["PJM_East"]["Scenario 0"], [0.1] * 6)
            audit = model["parcel_geography_vintage"]["coverage_audit"]
            self.assertEqual(audit["current_parcels_total"], 3)
            self.assertEqual(audit["parcels_without_tract_using_project_county_fallback"], 1)


def _write_cambium_fixture(path: Path) -> None:
    def column(number: int) -> str:
        letters = ""
        while number:
            number, remainder = divmod(number - 1, 26)
            letters = chr(ord("A") + remainder) + letters
        return letters

    def cell(reference: str, value: str | float) -> str:
        if isinstance(value, str):
            return f'<c r="{reference}" t="inlineStr"><is><t>{value}</t></is></c>'
        return f'<c r="{reference}"><v>{value}</v></c>'

    def row(number: int, cells: list[str]) -> str:
        return f'<row r="{number}">{"".join(cells)}</row>'

    component_starts = {"CO2_direct": 16, "CH4_direct": 64, "N2O_direct": 112,
                        "CO2_pre": 160, "CH4_pre": 208, "N2O_pre": 256}
    labels = {
        "CO2_direct": "CO2 from Direct Combustion (kg per MWh of end-use demand)",
        "CH4_direct": "CH4 from Direct Combustion (g per MWh of end-use demand)",
        "N2O_direct": "N2O from Direct Combustion (g per MWh of end-use demand)",
        "CO2_pre": "CO2 from Precombustion (kg per MWh of end-use demand)",
        "CH4_pre": "CH4 from Precombustion (g per MWh of end-use demand)",
        "N2O_pre": "N2O from Precombustion (g per MWh of end-use demand)",
    }
    annual_rows = [
        row(3, [cell(f"{column(col)}3", labels[key]) for key, col in component_starts.items()]),
        row(4, [cell(f"{column(16 + 6 * i)}4", f"Scenario {i}") for i in range(8)]),
        row(5, [cell(f"{column(16 + 6 * i + j)}5", float(2025 + j * 5)) for i in range(8) for j in range(6)]),
        row(6, [cell("B6", "PJM_East")] + [
            cell(f"{column(base + 6 * scenario + year)}6", 100.0 if key == "CO2_direct" else 0.0)
            for key, base in component_starts.items()
            for scenario in range(8)
            for year in range(6)
        ]),
    ]
    headers = ["State FIPS", "County FIPS", "County", "State Abbr", "State", "ReEDS BA", "Cambium GEA"]
    mapping_rows = [row(1, [cell(f"{column(i)}1", title) for i, title in enumerate(headers, 1)])]
    mapping_rows.append(row(2, [cell("A2", 42.0), cell("B2", 3.0), cell("C2", "Allegheny"),
                                cell("D2", "PA"), cell("E2", "Pennsylvania"),
                                cell("F2", "p115"), cell("G2", "PJM_East")]))
    gwp_rows = [row(7, [cell("B7", "100-year (AR6)"), cell("C7", 1.0), cell("D7", 29.8), cell("E7", 273.0)])]

    main_ns = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    rel_ns = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    package_ns = "http://schemas.openxmlformats.org/package/2006/relationships"
    workbook = (
        f'<workbook xmlns="{main_ns}" xmlns:r="{rel_ns}"><sheets>'
        '<sheet name="Data - Annual" sheetId="1" r:id="rId1"/>'
        '<sheet name="County Mapping" sheetId="2" r:id="rId2"/>'
        '<sheet name="GWP" sheetId="3" r:id="rId3"/>'
        '</sheets></workbook>'
    )
    relationships = (
        f'<Relationships xmlns="{package_ns}">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
        '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet2.xml"/>'
        '<Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet3.xml"/>'
        '</Relationships>'
    )
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("xl/workbook.xml", workbook)
        archive.writestr("xl/_rels/workbook.xml.rels", relationships)
        archive.writestr("xl/worksheets/sheet1.xml", f'<worksheet xmlns="{main_ns}"><sheetData>{"".join(annual_rows)}</sheetData></worksheet>')
        archive.writestr("xl/worksheets/sheet2.xml", f'<worksheet xmlns="{main_ns}"><sheetData>{"".join(mapping_rows)}</sheetData></worksheet>')
        archive.writestr("xl/worksheets/sheet3.xml", f'<worksheet xmlns="{main_ns}"><sheetData>{"".join(gwp_rows)}</sheetData></worksheet>')


if __name__ == "__main__":
    unittest.main()
