# Placeholder and source integration status

Structured facts are integrated by typed adapters. `data/config/assumptions.yaml`
contains citywide assumptions and fallbacks; parcel and tract observations stay
keyed to their geography in `data/processed/parcels.json`. Laya/LLM extraction is
reserved for unstructured documents and creates sourced candidates; it does not
replace deterministic joins or infer unsupported local values.

## Newly integrated evidence

| Input | Integration | Coverage and limits |
|---|---|---|
| 2024 ACS B19013 and B25070 | Tract estimates, MOEs, renter-burden numerator/denominator and approximate component-MOE envelope join to parcels | Income: 22,113/22,183; renter burden: 22,132/22,183. Config placeholders are fallbacks only for unavailable or suppressed tracts. |
| Allegheny County parcel polygons | Projected minimum-rotated-rectangle axes are stored as geometry-derived frontage/depth estimates when legal-description dimensions are absent | 5,965 lots estimated this run. Estimates support the lot drawing and rough form fit only; they are not legal frontage or survey dimensions. Remaining unmatched lots retain the fallback ratio. |
| EPA Smart Location Database 3.0 | D5DRI and D5BR joined by reconstructed 2020 block-group GEOID; D5DRI supplies the parcel transit-access metric and D5BR is shown as a source-linked site fact | 15,553/22,183 parcels matched. Vintage is 2021 (2020 GTFS/travel times, 2017 LEHD). Unmatched groups retain the fallback. Transit accessibility is not household VMT. |
| EPA passenger-vehicle factor | `kgco2e_per_vmt` is now a documented assumption at 0.393 kg CO2e/vehicle-mile, the EPA national passenger-vehicle tailpipe proxy | National 2022 fleet/fuel-economy baseline, not Pittsburgh-specific; this does not fill household VMT. |
| eGRID2023 / HUD 2024 HCC and TDC | Existing sourced electricity and development-cost assumptions remain in use | These were already integrated before this update; they are benchmarks, not bids or parcel observations. |

## Remaining placeholder decisions

| Assumption | Evidence path | Integration decision |
|---|---|---|
| `steep_slope_cost_share`, `landslide_cost_share`, `undermined_cost_share` | Geotechnical and subsurface reports for a proposed site; city screening layers are not cost schedules | Keep unknown/retire generic cost percentages. Do not infer a universal site premium from hazard flags. |
| `annual_capital_cost_share` | Explicit financing scenario terms | Replace with debt/equity/subsidy scenario inputs; no national average represents a project-specific capital stack. |
| `operating_cost_per_unit_month` | [Census 2024 RHFS](https://www.census.gov/data/developers/data-sets/rhfs/2024.html) | RHFS is national-only and reports 2023 operating expenses. A national benchmark can be shown with that scope; do not label it Pittsburgh observed data. |
| `embodied_kgco2e_psf` | [EC3 EPDs](https://docs.buildingtransparency.org/ec3/api-and-integrations) plus a declared material quantity schedule per typology | An LLM can locate EPD fields; deterministic quantity × factor calculation is needed for a whole-building estimate. |
| `operational_kwh_psf_yr` | [ResStock](https://resstock.nrel.gov/) for existing-stock context; EnergyPlus/OpenStudio prototypes for new typologies | Do not substitute existing-stock averages for new buildings. Model separately by building type and vintage. |
| `grid_decarbonization_per_yr` | [NREL Cambium](https://www.nrel.gov/analysis/cambium.html) scenario/year trajectories | Replace the scalar decline with an explicit year-indexed scenario series before applying it to the 30-year carbon calculation. |
| `vmt_per_household_yr` | [EPA Smart Location](https://www.epa.gov/smartgrowth/smart-location-mapping) does not publish household VMT; SPC model output may be usable if licensed and available | Keep unknown or remove travel emissions from ranked claims until a matching regional travel model is connected. Do not scale VMT inversely by transit access. |
| `lot_depth_to_frontage_ratio` | [Allegheny parcel boundaries](https://gisdata.alleghenycounty.us/arcgis/rest/services/OPENDATA/Parcels/MapServer/0) | Now only a fallback where both legal dimensions and a usable county polygon are missing. Geometry estimates are explicitly modeled, not legal frontage. |
| `tract_median_household_income` | [2024 ACS B19013](https://www.census.gov/data/developers/data-sets/acs-5year.html) | Used as a fallback only for missing/suppressed tract data; normal parcel results use the joined tract estimate and MOE. |
| `tract_renter_cost_burden_share` | [2024 ACS B25070](https://www.census.gov/data/developers/data-sets/acs-5year.html); [HUD CHAS](https://www.huduser.gov/portal/datasets/cp/CHAS/data_doc_chas.html) can add other cross-tabs | Used as a fallback only where the tract join is unavailable. CHAS is optional for metrics ACS cannot supply. |
| `jobs_access_index` | EPA SLD D5DRI | Parcel values are now joined. The assumption remains only for unmatched block groups; current values are relative to the highest-access CBG in the Pittsburgh CBSA, not city-average normalized. |
| `sewer_stress_index` | [ALCOSAN Clean Water Plan](https://www.alcosan.org/docs/default-source/clean-water-plan-documents/cwp-section-4.pdf?sfvrsn=6d0d892a_2), PWSA/ALCOSAN outfalls, [EPA ECHO inventory](https://echo.epa.gov/tools/data-downloads/cso-inventory-summary) | Keep stress/capacity unknown until observations can be joined by outfall or sewershed. The 2018 combined-sewershed overlay is not capacity or stress. |

The travel factor is no longer a placeholder, but its U.S. average scope is
visible in its assumption rationale. Source URLs, vintages, and integration
status are recorded in `data/config/sources.yaml` and `docs/SOURCES.md`. The Laya
candidate ledger remains separate from applied metrics; no metric is promoted
solely because an LLM produced a quote.
