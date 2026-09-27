# Estimate pipeline and remaining evidence gaps

The fourteen former numerical configuration placeholders now have source-backed
models, local donor estimates, or explicit planning budget scenarios. The
application reads the model artifacts directly and includes them in its cache
hash. This does not turn estimates into observations or close legal/design
confirmation questions.

| Input | Active calculation | Coverage and limits |
|---|---|---|
| Materials | Published gross A1–A3 single-family structure/enclosure/foundation benchmark, with declared form-proxy ranges | All 22,233 parcels, all six housing types. Partial physical/life-cycle scope; no biogenic credit. |
| Home electricity | DOE 2021 IECC climate-zone-5A heat-pump all-electric EnergyPlus outputs | All parcels/types. Detached and low-rise MF native prototypes; other forms receive explicit proxy sensitivity. |
| Grid path | Cambium 2024 Mid-case AER-load CO2e, official county mapping, annual interpolation | All parcels. Eight-pathway annual scenario spread; 2050 endpoint held afterward and disclosed. |
| Household driving | BTS LATCH 2017 weekday household VMT, annualized using NHTS 2017 national weekday/weekend driver-mile ratio | 15,581 same-code tract proxies; 6,652 county fallbacks, including 50 absent tract codes. No validated 2010/2024 tract-boundary crosswalk. |
| Driving emissions | EPA 2022 average U.S. gasoline passenger-vehicle tailpipe factor, 0.393 kgCO2e/mile | All parcels. Static national factor; future fleet, upstream fuel/vehicle impacts and EV charging omitted. |
| Sewer overflow context | ALCOSAN 2018 historical typical-year modeled outfall tables joined by documented PWSA labels | 14,948 direct outfall-context matches; 7,285 disclosed regional outfall-mean fallbacks. Not parcel discharge, current observation or capacity. |
| Missing income/rent burden | Median and donor percentile band from distinct matched Pittsburgh ACS tracts | Observed/sourced tract values take priority. Separate income and burden donor cohorts; geographic variation is not confidence. |
| Missing transit access | Median and donor band from distinct matched local EPA SLD block groups | Matched source values take priority. Transit access is not used to scale VMT. |
| Missing lot dimensions | Median legal-description depth/frontage ratio from local vacant parcels | Legal dimensions and polygon axes take priority. Donor-based drawing does not establish legal frontage. |
| Capital/operating aggregates | Explicit amortizing-debt/equity and line-item budget calculations with published rate references | Full parcel finance model takes priority. Loan terms and operating budgets remain scenarios requiring project quotes. |
| Hazard cost increments | Declared additional risk reserve blocks scaled to a PHFA 5% contingency reference | Zero included in ranges. Lotline selects the multipliers; these are budget stress scenarios, not modeled remediation costs or required safe-design reserves. |

## Still requiring better evidence

- Design-specific material quantities, missing assemblies and later life-cycle stages.
- Pittsburgh weather/design/occupancy energy models and future vehicle-fleet scenarios.
- Validated tract vintage crosswalk and current local household travel evidence.
- Current overflow models and verified sewershed/outfall topology for unresolved labels.
- Written utility capacity and availability, legal frontage, buildability, acquisition terms,
  and parcel-specific geotechnical/contractor/lender/operator findings.
- Planner-reviewed zoning interpretations and parcel overlays.

These remain visible questions. Historical regional estimates are useful context,
with their model boundary disclosed in each card's source breakdown.

See [environmental estimate methods](ENVIRONMENT_ESTIMATES.md),
[data sources](SOURCES.md), and the generated
`data/processed/environment_coverage.json` for exact coverage and model hashes.
