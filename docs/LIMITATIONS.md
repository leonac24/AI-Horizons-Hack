# Limitations

Lotline is **decision support**. It is not zoning, legal, or financial advice.
Confirm anything consequential with the City of Pittsburgh Department of City Planning.

## Current state (updated automatically)

<!-- AUTO:START -->
_Auto-generated for config `0b5630e45ee1`._

- **Vacant parcels indexed:** 22,233 (City of Pittsburgh only).
- **Zoning rules in force:** AI-extracted rules are in force once their quotes verify against the saved code text; they are labelled as not checked by a planner (`require_human_review` in zoning.yaml).
- **Share of vacant parcels covered by zoning rules:** 87.9% (7 of 41 base districts); by human-reviewed rules: 0.0%.
- **Largest base districts with no rules yet:** LNC (947), UI (463), NDI (186), RIV-MU (148), RIV-IMU (98), UPR-B (98), RIV-RM (88), RIV-NS (87), RP (80), (no district) (55), HC (53), GI (43).
- **Uses settled city-wide (1):** `single_unit_detached_with_adu`. These are decided by a rule that applies in every district, so they are excluded from the ranking everywhere, with a citation.
- **Placeholder assumptions (0):** none.
- **2024 ACS median income / renter burden:** 22,113 / 22,132 indexed lots have tract estimates.
- **FEMA point screen:** 22,192 classified; 360 in a mapped Special Flood Hazard Area at the tested point.
- **2018 PWSA combined sewersheds:** 19,447 indexed lots have a point match.
- **EPA SLD transit access:** 15,553 indexed lots have a 2021 block-group match (D5DRI relative access; D5BR weighted jobs within 45 minutes).
- **County geometry dimensions:** 5,971 lots have modeled parcel axes where legal dimensions were absent; these are not survey dimensions.
- **Sources not yet connected (4):** Comprehensive Housing Affordability Strategy (CHAS), Pittsburgh Regional Transit GTFS, Access Across America Transit 2024, ResStock.
<!-- AUTO:END -->

## What it gets wrong, or can't know

- **No zoning rule has been checked by a planner.** eCode360, which hosts Title
  Nine, blocks scripted access, so the code text was saved through a browser and
  the rules were extracted from it by AI; we do not write rules from memory.
  Every rule's quote is verified word for word against that saved text, and every
  answer one produces is labelled "AI-extracted … not checked by a planner".
  But none of the 171 extracted rules has been confirmed by a person yet, so the
  approval path on 87.9% of vacant lots — including every option excluded as
  prohibited — rests on an unchecked extraction. Lots in the 34 base districts
  with no rules show "Needs planner review". Only base districts are joined.
  Overlays (Riverfront, IPOD, historic districts) are not joined, and neither are
  planned-unit developments or specially planned districts.
- **Carbon values are partial modeled scenarios.** DOE climate-zone prototype
  electricity, a partial A1–A3 materials benchmark, annualized LATCH travel and
  Cambium grid pathways now replace numerical stand-ins for every parcel.
  Building-form and geographic proxies remain explicit. Materials omit
  interiors, MEP, appliances, site works, A4–A5 and later stages; driving omits
  future fleet changes and upstream fuel/vehicle impacts. These are not observed
  parcel emissions or complete whole-life totals.
- **Costs are declared planning budgets.** Source-based finance calculations
  use published rates, comparable sales where available, and declared financing
  and operating scenarios. Hazard reserve blocks are user-reviewable budget
  stress assumptions, not evidence of remediation cost or safe design.
- **Historical overflow models are context.** ALCOSAN 2018 typical-year outfall
  estimates are now matched by documented PWSA labels; unmatched parcels use a
  disclosed regional outfall mean. This is neither present-day overflow nor
  parcel discharge, causation or available utility capacity.
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
  The remaining lots use a disclosed median ratio from local legal-dimension donors. Geometry-derived dimensions are
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
