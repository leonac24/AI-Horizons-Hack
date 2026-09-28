"""Source-bounded residential carbon prototype inputs.

The checked-in values are scenario proxies, not measurements from Pittsburgh
homes. This module deliberately uses only the Python standard library at
runtime; the retrieval/parser used to make the checked-in DOE extract is an
optional CLI helper and is imported only when explicitly requested.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from statistics import mean as statistics_mean
from typing import Any

from core.artifact_files import replace_text

REPO_ROOT = Path(__file__).resolve().parents[1]
MODEL_PATH = REPO_ROOT / "data" / "models" / "carbon_prototypes.json"
ASSET_DIR = REPO_ROOT / "data" / "models" / "carbon_prototypes"
ENERGY_EXTRACT_PATH = ASSET_DIR / "doe_energy_outputs.json"
SOURCES_PATH = ASSET_DIR / "sources.json"
DOE_ZIP_URL = (
    "https://www.energycodes.gov/sites/default/files/2025-01/"
    "resstd_CZ5A_IECC_2021.zip"
)

_TYPOLOGY_SPECS: dict[str, dict[str, Any]] = {
    "detached": {
        "energy_proxy": "sf_detached",
        "label": "DOE 2021 IECC single-family detached; direct form match",
        "form_limitations": "Detached house maps to the DOE single-family detached form.",
        "energy_factor": (1.0, 1.0),
        "embodied_factor": (1.0, 1.0),
    },
    "adu_pair": {
        "energy_proxy": "sf_detached",
        "label": "DOE detached-house proxy for primary house plus ADU",
        "form_limitations": "DOE has no ADU prototype; this proxy does not separately model the ADU shell, foundation, shared or duplicated services.",
        "energy_factor": (0.75, 1.5),
        "embodied_factor": (0.75, 1.5),
    },
    "two_unit": {
        "energy_proxy": "sf_detached",
        "label": "DOE detached-house proxy for duplex",
        "form_limitations": "DOE residential set has no duplex form; shared walls, common systems and two-unit layout are not represented.",
        "energy_factor": (0.75, 1.5),
        "embodied_factor": (0.75, 1.5),
    },
    "rowhouse": {
        "energy_proxy": "sf_detached",
        "label": "DOE detached-house proxy for attached rowhouse",
        "form_limitations": "DOE residential set has no rowhouse form; party walls and repeated attached geometry are not represented.",
        "energy_factor": (0.75, 1.5),
        "embodied_factor": (0.75, 1.5),
    },
    "small_multi": {
        "energy_proxy": "mf_lowrise",
        "label": "DOE multifamily low-rise prototype for energy; DOE detached-house study for embodied carbon",
        "form_limitations": "Low-rise multifamily is an operational-energy prototype match. The embodied study has no multifamily ECI, so its detached-house center is only a reference; the wide 0.5–2.0 form multiplier is an explicit bounding assumption.",
        "energy_factor": (1.0, 1.0),
        "embodied_factor": (0.5, 2.0),
    },
    "midrise": {
        "energy_proxy": "mf_lowrise",
        "label": "DOE multifamily low-rise proxy for 5-story mid-rise; DOE detached-house study for embodied carbon",
        "form_limitations": "DOE residential energy outputs have no mid-rise residential prototype. Low-rise multifamily is an operational proxy; the detached-house ECI is only a reference. Both ranges are widened for transfer uncertainty.",
        "energy_factor": (0.75, 1.5),
        "embodied_factor": (0.5, 2.0),
    },
}

_ENERGY_SOURCE_IDS = (
    "doe_iecc2021_residential_cz5a_outputs",
    "pnnl_33270_allegheny_5a",
    "doe_pa_residential_code_status_2026",
)
_EMBODIED_SOURCE_IDS = (
    "jungclaus_2024_sf_embodied_a1a3",
)
_ENERGY_LIMITATIONS = (
    "Simulated 2021 IECC prototype electricity in Buffalo TMY3 weather, not a Pittsburgh meter or prediction. "
    "Assumes all-electric heat-pump systems; selected output tables have zero non-electric fuel use. "
    "Foundation low/high span four foundation variants only and are not a statistical interval. "
    "Building form, floor area, occupancy, schedules, appliance behavior and local weather may differ. "
    "DOE uses one single-family detached and one multifamily low-rise base form; other forms are explicit proxies."
)
_EMBODIED_LIMITATIONS = (
    "Upfront materials (A1-A3 proxy), not complete whole-building or whole-life carbon. "
    "The source covers DOE detached single-family models and structure/enclosure/foundation material classes; "
    "interiors/fit-out, MEP, appliances and sitework are not established as included. "
    "A4-A5 transport/construction, replacements/use and end-of-life are outside A1-A3. "
    "Source min/max spans study climate, foundation, and LCA-tool cases, not a confidence interval. "
    "Typology differences beyond the DOE detached archetype use declared proxy factors."
)


def build_prototype_model(
    energy_extract_path: Path | str = ENERGY_EXTRACT_PATH,
    sources_path: Path | str = SOURCES_PATH,
) -> dict[str, Any]:
    """Deterministically rebuild typology envelopes from checked-in source inputs."""
    energy = _read_json(Path(energy_extract_path))
    manifest = _read_json(Path(sources_path))
    source_by_id = {source["id"]: source for source in manifest["sources"]}
    embodied_source = source_by_id["jungclaus_2024_sf_embodied_a1a3"]
    reported_range = embodied_source["reported_result"]["eci_range_kgco2e_m2"]
    ec_low = reported_range[0] * 0.09290304
    ec_high = reported_range[1] * 0.09290304
    ec_center = (reported_range[0] + reported_range[1]) / 2 * 0.09290304
    energy_groups: dict[str, list[dict[str, Any]]] = {}
    for row in energy["rows"]:
        energy_groups.setdefault(row["prototype"], []).append(row)
    for rows in energy_groups.values():
        rows.sort(key=lambda row: row["foundation"])

    energy_urls = [url for source_id in _ENERGY_SOURCE_IDS for url in source_by_id[source_id]["urls"]]
    embodied_urls = list(embodied_source["urls"])
    if embodied_source.get("data_url"):
        embodied_urls.append(embodied_source["data_url"])
    by_typology: dict[str, Any] = {}
    for typology_id, spec in _TYPOLOGY_SPECS.items():
        native_rows = energy_groups[spec["energy_proxy"]]
        native_values = [row["electricity_kwh_per_conditioned_sf_yr"] for row in native_rows]
        energy_factor_low, energy_factor_high = spec["energy_factor"]
        embodied_factor_low, embodied_factor_high = spec["embodied_factor"]
        energy_has_adjustment = (energy_factor_low, energy_factor_high) != (1.0, 1.0)
        embodied_has_adjustment = (embodied_factor_low, embodied_factor_high) != (1.0, 1.0)
        embodied = {
            "value": round(ec_center, 2),
            "low": round(ec_low * embodied_factor_low, 2),
            "high": round(ec_high * embodied_factor_high, 2),
            "unit": "kgCO2e/sf",
            "provenance": "modeled",
            "evidence_tier": "modeled_prototype_lca",
            "interval_type": (
                "reported_study_range_plus_assumed_form_factor"
                if embodied_has_adjustment else "reported_study_range"
            ),
            "geography": embodied_source["geography"],
            "source_ids": list(_EMBODIED_SOURCE_IDS),
            "source_urls": embodied_urls,
            "model_id": "us_doe_sfh_embodied_ec_intensity_a1_a3_2024",
            "source_range_kgco2e_m2": {
                "low": reported_range[0], "high": reported_range[1], "unit": "kgCO2e/m2",
            },
            "reported_stage_boundary": (
                "A1-A3 product-stage embodied GHG; gross ECI, without applying "
                "separately reported theoretical maximum biogenic storage"
            ),
            "physical_scope": "DOE single-family prototype quantity takeoff: structure, enclosure, and foundation material classes",
            "center_basis": (
                f"Arithmetic midpoint of the published {reported_range[0]}–{reported_range[1]} kgCO2e/m2 "
                f"all-model ECI range ({(reported_range[0] + reported_range[1]) / 2:g} kgCO2e/m2 converted "
                f"to {round(ec_center, 2):.2f} kgCO2e/sf); declared planning center, not a reported sample mean."
            ),
            "proxy_adjustment": {
                "low_factor": embodied_factor_low,
                "high_factor": embodied_factor_high,
                "provenance": "assumption" if embodied_has_adjustment else "none",
                "limitations": spec["form_limitations"],
            },
            "as_of": embodied_source["publication_date"],
            "limitations": _EMBODIED_LIMITATIONS,
        }
        energy_envelope = {
            "value": round(statistics_mean(native_values), 2),
            "low": round(min(native_values) * energy_factor_low, 2),
            "high": round(max(native_values) * energy_factor_high, 2),
            "unit": "kWh/sf/yr",
            "provenance": "modeled",
            "evidence_tier": "doe_energyplus_prototype_output",
            "interval_type": (
                "foundation_range_plus_assumed_form_proxy"
                if energy_has_adjustment else "foundation_variant_range"
            ),
            "geography": (
                "IECC 2021 climate zone 5A; DOE uses Buffalo Niagara International Airport TMY3; "
                "Allegheny County is also CZ5A but Buffalo weather is not Pittsburgh local weather"
            ),
            "source_ids": list(_ENERGY_SOURCE_IDS),
            "source_urls": energy_urls,
            "model_id": "doe_iecc2021_residential_cz5a_heat_pump",
            "prototype_proxy": spec["energy_proxy"],
            "scenario": (
                "All-electric heat-pump scenario. Uses only DOE hp-tagged output tables; "
                "all non-electric fuel columns in selected annual end-use outputs are zero."
            ),
            "end_uses": "Electricity:Facility annual meter for all modeled end uses, normalized by Net Conditioned Building Area.",
            "foundation_variants": [
                {
                    "foundation": row["foundation"],
                    "model_id": row["model_id"],
                    "electricity_facility_meter_kwh_yr": row["electricity_facility_meter_kwh_yr"],
                    "conditioned_area_sf": row["conditioned_area_sf"],
                    "value_kwh_sf_yr": row["electricity_kwh_per_conditioned_sf_yr"],
                }
                for row in native_rows
            ],
            "center_basis": "Arithmetic mean of the four DOE HP foundation variant EUIs for the selected prototype; no building-form savings are assumed.",
            "proxy_adjustment": {
                "low_factor": energy_factor_low,
                "high_factor": energy_factor_high,
                "provenance": "assumption" if energy_has_adjustment else "none",
                "limitations": spec["form_limitations"],
            },
            "as_of": source_by_id[_ENERGY_SOURCE_IDS[0]]["publication_date"],
            "limitations": _ENERGY_LIMITATIONS,
        }
        by_typology[typology_id] = {
            "proxy_label": spec["label"],
            "embodied_kgco2e_psf": embodied,
            "operational_kwh_psf_yr": energy_envelope,
        }
    return {
        "schema_version": 1,
        "source_vintage": (
            "DOE 2021 IECC residential HP prototype outputs; output tables generated "
            "2024-06-27 / posted 2024-12-22; embodied study published 2024-12-15"
        ),
        "geography": "Pittsburgh (Allegheny County) IECC climate-zone proxy 5A; DOE weather model is Buffalo NY TMY3",
        "by_typology": by_typology,
        "sources_manifest": "data/models/carbon_prototypes/sources.json",
        "energy_extract": "data/models/carbon_prototypes/doe_energy_outputs.json",
    }


def write_prototype_model(destination: Path | str = MODEL_PATH) -> dict[str, Any]:
    """Write a deterministic, network-free model JSON from source assets."""
    model = build_prototype_model()
    output = Path(destination)
    output.parent.mkdir(parents=True, exist_ok=True)
    replace_text(output, json.dumps(model, indent=2, ensure_ascii=False) + "\n")
    return model


def build_prototype_inputs(typology_id: str, *, allow_missing: bool = False) -> dict[str, Any]:
    """Return modeled embodied and operational envelopes for one typology.

    The center of the embodied envelope is the explicitly assumed midpoint of
    a published prototype-study range. Operational centers are the arithmetic
    mean of the four DOE foundation alternatives for the selected prototype.
    """
    data = _load_model()
    try:
        record = data["by_typology"][typology_id]
    except KeyError as exc:
        if allow_missing:
            return {}
        raise KeyError(f"unknown housing typology: {typology_id}") from exc
    return json.loads(json.dumps(record))


def build_prototype_evidence() -> dict[str, Any]:
    """Return evidence-envelope objects with ``by_typology`` for Lotline."""
    data = _load_model()
    ids = data["by_typology"]
    result: dict[str, Any] = {}
    for key in ("embodied_kgco2e_psf", "operational_kwh_psf_yr"):
        shared = {
            "unit": ids["detached"][key]["unit"],
            "provenance": "modeled",
            "evidence_tier": "modeled_prototype",
            "interval_type": "proxy_range",
            "geography": "Pittsburgh planning scenario using declared U.S. residential prototypes",
            "source_ids": sorted({
                sid for record in ids.values() for sid in record[key]["source_ids"]
            }),
            "as_of": data["source_vintage"],
            "limitations": (
                "Typology-level prototype scenario, not an observed building or a "
                "parcel-specific prediction. See each by_typology envelope for proxy scope."
            ),
            "by_typology": {typology_id: record[key] for typology_id, record in ids.items()},
        }
        result[key] = shared
    return json.loads(json.dumps(result))


def _load_model() -> dict[str, Any]:
    stat = MODEL_PATH.stat()
    return _load_model_cached(str(MODEL_PATH), stat.st_mtime_ns, stat.st_size)


def _read_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as stream:
        return json.load(stream)


@lru_cache(maxsize=4)
def _load_model_cached(path: str, mtime_ns: int, size: int) -> dict[str, Any]:
    del mtime_ns, size  # cache key invalidates when the served model changes
    with Path(path).open(encoding="utf-8") as stream:
        data = json.load(stream)
    if data.get("schema_version") != 1:
        raise ValueError(f"unsupported carbon prototype schema in {path}")
    return data


def download_and_extract_doe_outputs(destination: Path | str = ENERGY_EXTRACT_PATH,
                                     *, source_zip: Path | str | None = None) -> dict[str, Any]:
    """Download and extract official DOE 2021 IECC 5A HP end-use output tables.

    This is an optional maintainer helper, not used by the application. Network,
    ZIP, and HTML parsing dependencies are loaded only inside this function.
    The output records source values and arithmetic so the checked-in model can
    be regenerated and audited without runtime downloads.
    """
    from hashlib import sha256
    from urllib.request import Request, urlopen
    from zipfile import ZipFile

    try:
        from bs4 import BeautifulSoup
    except ImportError as exc:  # pragma: no cover - maintainer-only workflow
        raise RuntimeError("install beautifulsoup4 to refresh DOE output extracts") from exc

    if source_zip is not None:
        package = Path(source_zip).read_bytes()
    else:
        request = Request(DOE_ZIP_URL, headers={"User-Agent": "Lotline prototype data refresh"})
        with urlopen(request, timeout=60) as response:
            package = response.read()
    package_hash = sha256(package).hexdigest()
    manifest = _read_json(SOURCES_PATH)
    expected = next(source["sha256"] for source in manifest["sources"]
                    if source["id"] == "doe_iecc2021_residential_cz5a_outputs")
    if package_hash != expected:
        raise ValueError("DOE package differs from the pinned source; review and curate the source vintage before refreshing")
    rows: list[dict[str, Any]] = []
    with ZipFile(__import__("io").BytesIO(package)) as archive:
        for prototype in ("SF", "MF"):
            for foundation in ("slab", "crawlspace", "heatedbsmt", "unheatedbsmt"):
                filename = (
                    f"US+{prototype}+CZ5A+hp+{foundation}+IECC_2021.table.htm"
                )
                html = archive.read(filename)
                soup = BeautifulSoup(html, "html.parser")
                conditioned_area = None
                facility_kwh = None
                fuel_end_uses: dict[str, float] = {}
                for table in soup.find_all("table"):
                    table_rows = [
                        [cell.get_text(" ", strip=True) for cell in row.find_all(["td", "th"])]
                        for row in table.find_all("tr")
                    ]
                    flattened = " ".join(" ".join(row) for row in table_rows)
                    if "Net Conditioned Building Area" in flattened:
                        for row in table_rows:
                            if row and row[0] == "Net Conditioned Building Area":
                                conditioned_area = float(row[1].replace(",", ""))
                    if "Electricity Annual Value [kWh]" in flattened:
                        for row in table_rows:
                            if row and row[0] == "Electricity:Facility":
                                facility_kwh = float(row[1].replace(",", ""))
                    if "Electricity [kBtu]" in flattened and any(row and row[0] == "Total End Uses" for row in table_rows):
                        for row in table_rows:
                            if row and row[0] == "Total End Uses":
                                header = next(
                                    candidate for candidate in table_rows
                                    if candidate and "Electricity [kBtu]" in candidate
                                )
                                fuel_end_uses = {
                                    name.removesuffix(" [kBtu]"): float(value.replace(",", ""))
                                    for name, value in zip(header[1:], row[1:])
                                    if "[kBtu]" in name
                                }
                if not conditioned_area or facility_kwh is None or not fuel_end_uses:
                    raise ValueError(f"required EnergyPlus table missing from {filename}")
                if any(value != 0 for name, value in fuel_end_uses.items() if name != "Electricity"):
                    raise ValueError(f"selected HP output is not all-electric: {filename}")
                rows.append({
                    "model_id": filename.removesuffix(".table.htm"),
                    "prototype": "sf_detached" if prototype == "SF" else "mf_lowrise",
                    "foundation": foundation,
                    "conditioned_area_sf": conditioned_area,
                    "electricity_facility_meter_kwh_yr": facility_kwh,
                    "fuel_end_uses_kbtu_yr": fuel_end_uses,
                    "electricity_kwh_per_conditioned_sf_yr": round(facility_kwh / conditioned_area, 8),
                })
    # The pinned package's curated publication/generation dates and accounting
    # notes remain valid; only extracted meter, area and fuel rows are rebuilt.
    result = {
        **_read_json(ENERGY_EXTRACT_PATH),
        "source_id": "doe_iecc2021_residential_cz5a_outputs",
        "source_url": DOE_ZIP_URL,
        "package_sha256": package_hash,
        "rows": rows,
    }
    output = Path(destination)
    output.parent.mkdir(parents=True, exist_ok=True)
    replace_text(output, json.dumps(result, indent=2) + "\n")
    return result


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--refresh", action="store_true", help="regenerate from pinned source extracts")
    parser.add_argument("--download-doe", action="store_true", help="re-extract the pinned official DOE package (requires beautifulsoup4)")
    parser.add_argument("--doe-zip", type=Path, help="re-extract a cached pinned DOE package offline")
    parser.add_argument("--output", type=Path, default=MODEL_PATH)
    args = parser.parse_args()
    if not args.refresh:
        parser.error("specify --refresh")
    if args.download_doe or args.doe_zip:
        download_and_extract_doe_outputs(source_zip=args.doe_zip)
    model = write_prototype_model(args.output)
    print(f"Wrote modeled carbon inputs for {len(model['by_typology'])} housing types")
