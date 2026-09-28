# Environmental estimates used by the application

The application reads compact, checked-in source extracts in `data/models/`.
It resolves a model for every indexed Pittsburgh parcel, including parcels
without a tract or combined-sewershed match. Geographic fallbacks and building
form proxies are disclosed in each input envelope. Model files are included in
the API analysis hash so refreshed data invalidate cached calculations.

## Building inputs

- Electricity uses DOE/PNNL **2021 IECC climate-zone-5A heat-pump** prototype
  outputs: the annual electricity facility meter divided by conditioned floor
  area. The selected outputs have zero use of other energy carriers. Buffalo
  representative weather is a climate-zone proxy for Pittsburgh. Foundation
  alternatives provide native prototype sensitivity; non-native housing forms
  receive an additional declared proxy range.
- Materials use the published 2024 U.S. single-family benchmark study's gross
  **A1–A3 structure, enclosure and foundation** intensity range. Its midpoint
  is a declared central scenario. It is transferred to other forms with a
  wider declared range. This is not a design-specific bill of materials.
- Interior fit-out, MEP, appliances, site works, A4–A5 transport/installation,
  replacements, demolition and end-of-life are not quantified by this material
  proxy. No biogenic-storage credit is subtracted. The carbon card is labeled a
  partial scenario and must not be described as a complete whole-life total.

Source extracts, hashes, model choices, units and regeneration helpers are in
`pipeline/carbon_prototypes.py` and `data/models/carbon_prototypes/`.

## Grid and household travel

- Cambium 2024 supplies a named **Mid-case AER-load CO2e** regional trajectory;
  the range spans the available modeled scenarios. The official county mapping
  goes through a ReEDS balancing area to its model region. AER-load includes
  upstream fuel emissions and average distribution losses; no additional grid
  loss factor is added. This differs from the historical eGRID output-rate
  boundary, which remains a separate reference.
- The source's five-year points are interpolated to annual values. The last
  modeled year is held constant when the requested horizon extends beyond the
  source horizon; that extrapolation is reported on the returned carbon model.
- BTS LATCH 2017 gives modeled weekday household vehicle miles at 2010 tract
  geography. Same-code tract matches are explicitly **2010-code proxies**,
  not verified 2024-to-2010 boundary crosswalks. Unmatched and absent tract
  codes use an Allegheny County household-weighted estimate.
- Annualization uses a disclosed transfer of the 2017 NHTS national
  weekend/weekday driver-mile ratio to LATCH household weekday miles. The
  source MOE endpoints provide ratio sensitivity, not a confidence interval
  for annual household travel. Model reliability flags remain in the envelope.
- Driving uses EPA's 2022 average gasoline passenger-vehicle tailpipe factor.
  Future fleet electrification, upstream vehicle/fuel impacts and EV charging
  are not supplied by this driving calculation.

Source extracts and model choices are in `pipeline/carbon_geography.py` and
`data/models/carbon_geography.json`.

## ALCOSAN modeled overflow context

The Clean Water Plan Section 4 tables supply **historical typical-year modeled
outfall overflow** values. Only documented identifier normalization is used to
match a PWSA combined-sewershed label to a report outfall. No nearest-outfall
assignment is performed. Unmatched parcels receive a clearly labeled regional
model fallback. Source table/page references and matching details are retained.

The overflow-pressure index is a disclosed comparison to the model's outfall
baseline. It is contextual: it does not quantify a parcel's discharge,
contribution to an overflow, available pipe capacity or the effect of a new
housing proposal. The infrastructure card continues to show proposed design
flow separately. Utility capacity remains a confirmation question.

Source rows and parser are in `data/models/alcosan_overflows.json` and
`pipeline/overflow_context.py`.

## Other former numerical stand-ins

Unmatched income, rent burden, transit access and lot depth/frontage use
reproducible local donor estimates. Donor percentile bands describe geographic
variation, not confidence intervals for the unmatched parcel. Legal dimensions,
survey findings and zoning approval are not inferred from these estimates.

Legacy capital and operating defaults are calculated from the declared finance
budget. Slope, landslide and mine-risk percentages are now explicitly declared
**additional budget reserve scenarios**, scaled in 5% reference blocks. The
PHFA contingency reference supports the block scale; Lotline selects the risk
multipliers. These are not empirical hazard premiums, remediation estimates,
required reserves or evidence of a safe site design. Their ranges include zero.
The full parcel finance model takes precedence over legacy aggregate defaults.

## Reproduce and inspect coverage

Install offline pipeline dependencies with `uv sync --group pipeline`. Model
queries in the running application need no GIS/HTML/PDF libraries or network.
For a source refresh:

```bash
python -m pipeline.carbon_prototypes --refresh --download-doe
python -m pipeline.carbon_geography --refresh
python -m pipeline.overflow_context --refresh
python -m pipeline.build_environment --refresh-metadata
python -m pipeline.docs
```

DOE can read a cached package with `--doe-zip PATH`; omitting download flags
rebuilds from checked-in extracts. Geography accepts `--latch-csv PATH` and
`--cambium-xlsx PATH` for offline refresh. Overflow accepts `--pdf PATH` and
requires Poppler's `pdftotext` only for extraction. Pinned DOE/ALCOSAN checksums
reject a different source vintage until it is reviewed and curated.

The analysis-only metadata refresh preserves parcel values, locations, cohorts
and source vintages. It records the original parcel-build configuration hash,
refresh scope, and active analysis hash; it also rebuilds the local donor and
declared budget models. Downloads/raw source files stay outside deployment.

`data/processed/environment_coverage.json` records the actual PIN denominator,
field coverage by evidence tier, model artifact hashes and example parcels.
`GET /api/unknowns` includes resolved model-input coverage, and
`GET /api/analysis/{PIN}` includes the actual inputs used in each carbon card.
The browser's “Built from” list reads those resolved inputs, so a geographic
estimate is not obscured by an unused citywide configuration value.

Coverage is read from the offline audit when its configuration and actual-data
hash match. A refresh without rebuilding the audit causes a single cached
recount. Data refreshes publish complete files by atomic replacement, so the API
can serve the prior complete snapshot until the new one is ready.
