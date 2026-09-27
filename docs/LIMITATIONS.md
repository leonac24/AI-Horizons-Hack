# Limitations

Lotline is **decision support**. It is not zoning, legal, or financial advice.
Confirm anything consequential with the City of Pittsburgh Department of City Planning.

## Current state (updated automatically)

<!-- AUTO:START -->
_Auto-generated for config `ccee62af18d1`._

- **Vacant parcels indexed:** 22,183 (City of Pittsburgh only).
- **Zoning rules in force:** AI-extracted rules are in force once their quotes verify against the saved code text; they are labelled as not checked by a planner (`require_human_review` in zoning.yaml).
- **Share of vacant parcels covered by zoning rules:** 88.1% (7 of 41 base districts); by human-reviewed rules: 0.0%.
- **Largest base districts with no rules yet:** LNC (949), UI (460), NDI (185), RIV-MU (148), UPR-B (98), RIV-IMU (97), RIV-RM (88), RIV-NS (87), RP (77), HC (52), GI (42), AP (41).
- **Uses settled city-wide (1):** `single_unit_detached_with_adu`. These are decided by a rule that applies in every district, so they are excluded from the ranking everywhere, with a citation.
- **Placeholder assumptions (14):** `steep_slope_cost_share`, `landslide_cost_share`, `undermined_cost_share`, `annual_capital_cost_share`, `operating_cost_per_unit_month`, `embodied_kgco2e_psf`, `operational_kwh_psf_yr`, `grid_decarbonization_per_yr`, `vmt_per_household_yr`, `lot_depth_to_frontage_ratio`, `tract_median_household_income`, `tract_renter_cost_burden_share`, `jobs_access_index`, `sewer_stress_index`.
- **2024 ACS median income / renter burden:** 22,113 / 22,132 indexed lots have tract estimates.
- **FEMA point screen:** 22,183 classified; 359 in a mapped Special Flood Hazard Area at the tested point.
- **2018 PWSA combined sewersheds:** 19,444 indexed lots have a point match.
- **EPA SLD transit access:** 15,553 indexed lots have a 2021 block-group match (D5DRI relative access; D5BR weighted jobs within 45 minutes).
- **County geometry dimensions:** 5,965 lots have modeled parcel axes where legal dimensions were absent; these are not survey dimensions.
- **Sources not yet connected (5):** Comprehensive Housing Affordability Strategy (CHAS), Pittsburgh Regional Transit GTFS, Access Across America Transit 2024, ALCOSAN / PWSA combined sewer overflow data, ResStock.
<!-- AUTO:END -->

## What it gets wrong, or can't know

- **Zoning is not yet reviewed.** eCode360, which hosts Title Nine, blocks
  scripted access, and we do not write rules from memory. Until a person
  extracts and reviews a district's rules, every lot there shows
  "Needs planner review". Only base districts are joined. Overlays (Riverfront,
  IPOD, historic districts) are not joined, and neither are planned-unit
  developments or specially planned districts.
- **Most cost and carbon numbers remain assumptions or placeholders.** HUD FY2026
  Pittsburgh area median family income is published, and 2024 ACS tract income
  and renter burden estimates are joined where available. Construction cost,
  soft cost, capital cost, operating cost, embodied and operational carbon,
  grid trajectory, household VMT and sewer stress still use assumptions or
  stand-ins. EPA transit access is joined for matched block groups; unmatched
  parcels retain the fallback. The UI hatches values that depend on a placeholder.
- **Mapped site context is checked at a point.** Slope, landslide and undermining
  use the published parcel centroid. FEMA flood and PWSA combined-sewershed
  screens use a point inside the county parcel polygon when its PIN matches,
  otherwise the published centroid. Part of a lot can cross a boundary without
  its tested point doing so. A flood result is not a site-specific FEMA
  determination. A combined-sewershed match is not sewer capacity or stress.
- **"Vacant" means the county's vacant land-use classes.** Lots with a condemned
  or abandoned structure are not included. Some coded-vacant lots are side yards,
  parking, or slivers that can't be built on.
- **The 3D city is stylized.** Terrain comes from public elevation tiles (AWS
  Terrain Tiles, derived from USGS 3DEP/SRTM) with heights exaggerated for
  legibility, and rivers are wherever that terrain sits at the normal pool
  level. City blocks, trees, bridge models and the neighbors around each lot
  are decorative; bridge positions come from the design handoff and were not
  independently verified. Parcel positions (centroids) and lot dimensions are
  real. None of this scenery feeds any metric.
- **Lot shape is a rectangle.** Frontage × depth comes from the deed legal
  description when it agrees with assessed area (about 71% of vacant parcels),
  otherwise from approximate axes of a matched county parcel polygon (about 27%).
  The remaining lots use a placeholder ratio. Geometry-derived dimensions are
  modeled, not legal frontage or survey measurements. Irregular, corner and
  through-lots are drawn as rectangles, and the building fit is a screen, not a
  site plan: no setbacks, access or topography.
- **Homes per building are assumptions** (`typologies.yaml: building.homes`),
  consistent with the configured unit sizes.
- **Assessed land value is not a market price.** It is used only as a land-cost
  input and is often far below what a lot would sell for.
- **Unit counts come from built form, not a feasibility study.** They are
  planning rules of thumb for lot area per home. Parking, access, utility
  capacity, and topography beyond the flags are not modeled.
- **Rent needed to cover cost is a simple annualized model** (capital cost share
  plus operating cost). It is not a pro forma: no financing structure, tax
  credits, abatements, or market rents.
- **Transit access uses an older regional snapshot.** EPA SLD 3.0 provides a
  2021 block-group relative-access measure and weighted jobs within 45 minutes;
  it is not a current route-level travel-time model or household VMT estimate.
- **City limits only.** Other Allegheny County municipalities have their own
  zoning codes.
- **Next steps name an agency, not a person, and the links are unconfirmed.**
  Land Bank, URA, City Real Estate and City Planning contacts in
  `next_steps.yaml` were found by web search; the pages could not be opened from
  the build environment, so each shows "not yet confirmed" until a teammate
  checks it and sets `checked: true`. Which agency handles a public lot is read
  from the city inventory's type; that routing is our reading, not the city's.
- **Lotline does not know which Registered Community Organization covers a lot.**
  WPRDC publishes RCO boundaries, but they are not joined to the parcel index
  yet, so the neighborhood step and handout point to the City's RCO list instead
  of naming an organization.
- **Outreach drafts are starting points.** They state only the facts on the step
  card, but the user is responsible for what they send.

## Who could be harmed by misuse

- **Residents of the neighborhoods shown.** A ranking can look like a
  recommendation. It is the arithmetic consequence of whichever weights the user
  picked. Using it to justify a project without community process would misuse
  it.
- **Owners of the parcels shown.** Showing a privately owned lot as a
  "housing opportunity" does not mean it is available. We do not show owner
  names.
- **Low-income households.** Affordability verdicts use placeholder costs and
  the 30%-of-income rule. A "Yes" is not an eligibility or pricing
  determination.

## What we don't claim

- That any lot can be built on, or that any option is permitted.
- That the stakeholder presets reflect what real organizations want. They are
  illustrative.
- That illustrative households are real people. They are synthetic.
- That the LLM explanation adds facts. It may only restate computed metrics,
  and the server rejects anything else.

## Reconciling sources

- Parcel IDs (PARID/PIN) join assessments, centroids and city-owned properties.
  About 50 vacant parcels had no centroid and are dropped (see
  `data/processed/pipeline_report.json`).
- Census geography comes from the WPRDC centroid file (March 2025 vintage).
  The 2024 ACS 5-year release uses 2020-era tract GEOIDs. Special-use tracts may
  have suppressed or non-computable income or burden estimates; these fall back
  to visibly labeled placeholders, not zero. Renter burden excludes ACS
  “not computed” households from its denominator. Its range is an approximate
  envelope from component margins of error, not a Census-published ratio MOE.
