# Methods

Two layers, kept apart on purpose:

- **Evidence** (`core/engine.py`) computes each metric per housing type with a
  range and a provenance. No weight ever enters it.
- **Values** (`web/src/lib/scoring.ts`, mirrored in `core/scoring.py`) combine
  the evidence using weights that the user controls.

Model parameters come from `data/config/assumptions.yaml`; joined site estimates
come from the processed parcel index. Housing types come from `typologies.yaml`,
and criteria and their directions from `criteria.yaml`.

## Uncertainty ranges

Each assumption has `value`, `low` and `high`. The engine evaluates each formula
once at the central values, then 300 more times with every assumption drawn
uniformly from [low, high] (seeded, so results are stable). A metric reports
the central value plus the 5th–95th percentile of the draws.

**Provenance** is the weakest input. If any placeholder feeds a metric, the
metric is a placeholder. Otherwise the order runs modeled, then assumption, then
observed.

For a lot with a valid 2024 ACS tract match, `B19013_E001` supplies median
household income and its published 90% MOE supplies the sample envelope. Renter
gross-rent burden is `(B25070_E007 + E008 + E009 + E010) / (E001 − E011)`.
The denominator excludes “not computed.” The ratio envelope uses the component
MOEs conservatively and is **not** an official Census ratio MOE. Missing or
suppressed estimates retain the documented placeholder. The tract's estimate
does not describe any particular household or lot.

## Homes per lot (buildings that fit, not zoning)

Each typology defines one building in `typologies.yaml`: a footprint (width
along the street × depth, in feet) and the number of homes in it. The option
shown for a lot is as many of those buildings as fit side by side along the
frontage:

    fits       = footprint_w ≤ frontage and footprint_d ≤ depth and lot_area ≥ min_lot_sf_for_form
    buildings  = min(max_in_a_row, floor(frontage / footprint_w))     (1 if it doesn't fit)
    homes      = buildings × homes_per_building

These are the same buildings the 3D lot view places, so what you see ranked is
what "Place" puts on the lot. It is a geometric screen: setbacks, access,
parking and topography are not modeled.

**Lot shape.** For about 71% of vacant parcels, the deed legal description
gives dimensions ("LOT 30X100"). We use them only when frontage × depth agrees
with the assessed lot area (within 0.6–1.6×); these are **observed**. Otherwise
the lot is drawn from its area and a placeholder depth-to-frontage ratio
(`lot_depth_to_frontage_ratio`), and marked **placeholder**.

## Your plan (mixed buildings)

`POST /api/analysis/{id}/plan` takes building counts per type. Each type runs
through the same engine at the homes the plan gives it, and the results are
combined:

- **Counts add up:** homes, homes serving local need, and infrastructure load.
- **Per-home measures are averaged, weighted by homes:** income needed, monthly
  cost, share above local rents, and carbon per household.
- **Zoning takes the most restrictive path** among the plan's building types.
  Dimensional rules are checked against the plan's total homes.
- **Prohibited types:** any building type whose use is prohibited is flagged,
  and the plan is excluded from the ranking.

## Cost and affordability

    gross_sf       = homes × unit_size_sf
    site_share     = Σ cost_share of each hazard flag present (steep slope, landslide, undermined)
    dev_cost       = gross_sf × hard_cost_psf × (1 + soft_cost_share + site_share) + assessed_land_value
    monthly_cost   = dev_cost / homes × annual_capital_cost_share / 12 + operating_cost_per_unit_month
    income_needed  = monthly_cost × 12 / housing_cost_share            (housing_cost_share = 0.30)
    ami_needed_pct = income_needed / ami_4person × 100

**"Could this household afford it?"** A household's income is
`ami_4person × size_factor(size) × ami_pct`, using HUD's size adjustment. It can
afford `income × 0.30 / 12` per month.

- **Yes**: that amount covers the high end of the monthly cost range.
- **No**: it falls below the low end.
- **Maybe**: anything in between.

## Criteria

Every criterion can differ between housing types on the same lot. Lot-level
facts appear once, under "About this lot".

| Criterion | Formula | Direction |
|---|---|---|
| Serves local housing need | `homes × renter_cost_burden_share × min(1, tract_median_income / income_needed)` | higher better |
| Zoning path | reviewed status → score (`zoning_status_score.by_key`); unreviewed → placeholder spanning all outcomes | higher better |
| Income needed | `ami_needed_pct` | lower better |
| Share priced above nearby renter incomes | `1 − min(1, tract_median_income / income_needed)` | lower better |
| Strain on infrastructure | `homes × (1 + Σ hazard weights present) × sewer_stress_index` | lower better |
| Carbon per household | see below | lower better |

Two changes on 2026-09-26, both to stop the criteria overstating what the
evidence supports:

**"Adds displacement pressure" became "Share priced above nearby renter
incomes."** It was `homes × renter_cost_burden_share × (1 − affordability
ratio)` — three uncertain inputs multiplied and reported as a count of whole
homes — under a name that asserted a causal claim. Estimating households
displaced needs longitudinal data and a validated causal method that we do not
have for Pittsburgh parcels. It is now a share, and it is named for what it
measures.

**"Households gaining job access" was removed as a criterion.** It was
`homes × jobs_access_index`, and `jobs_access_index` is a property of the lot,
not of the housing type. Within a single lot it was therefore a positive
constant times unit count — which, after min–max normalization, is exactly the
negative of "Strain on infrastructure". The two cancelled, so only the
*difference* between their two weights did any work, while both sliders appeared
to the user to be independent. Transit access is still computed and shown as
site context (`site.jobs_access`). If a future access measure varies by housing
type, it belongs back in this table.

## Carbon over time (per household)

    year 0:  embodied = embodied_kgco2e_psf × unit_size_sf / 1000                         (t)
    year y:  energy   = operational_kwh_psf_yr × unit_size_sf × grid_kgco2e_per_kwh × (1 − decarb)^(y−1)
             travel   = vmt_per_household_yr / jobs_access_index × kgco2e_per_vmt
    cumulative(y) = embodied + Σ (energy + travel) / 1000

A **crossover year** is the first year one option's cumulative line crosses
another's. It happens when one option costs more carbon to build but less to
live in.

## Scoring

1. For each criterion, normalize across the housing types on this lot:
   `n = (x − min) / (max − min)`, flipped for lower-is-better. A criterion with
   no spread scores 0.5 for every option.
2. Score = Σ wⱼ nⱼ, with weights normalized to sum to 1.

## SMAA (how often does each option rank first?)

The app runs N rounds (`app.yaml: smaa.samples`, seeded). Each round:

- draws weights from a Dirichlet centered on the current weights (concentration
  `profile_concentration`), or a uniform Dirichlet if there are none;
- draws every metric uniformly from its [low, high] range;
- scores and ranks the options.

The rank-acceptability index `acc[i][r]` is the share of rounds in which option
i took rank r. Each row and each column sums to 1.

## Ranking flip

Take the top option A and the runner-up B. Set criterion j's normalized weight
to t, and rescale the others by (1−t)/(1−wⱼ). The score gap is then linear in t:

    gap(t) = R (1−t)/(1−wⱼ) + Dⱼ t,   D = N[A] − N[B],   R = D·w − Dⱼ wⱼ
    t*     = r / (r − Dⱼ),  r = R / (1−wⱼ)

The sentence reports the criterion j with t* in [0, 1] that needs the smallest
|t* − wⱼ|.

## Zoning

`pipeline/zoning/extract.py` sends Title Nine text to an LLM (Gemini). Each rule
it returns must quote the supplied text verbatim, in fewer than 25 words.
Otherwise the rule is dropped. Rules land in `rules_review.yaml` with
`reviewed: false`. Only rules a person marks `reviewed: true` affect the app.

- A use rule sets the approval path.
- Reviewed dimensional rules (minimum lot area, lot area per unit, stories) are
  checked against the lot.
- Any failed dimensional rule turns the status into "variance needed", with its
  citation.

## Work backwards

For a target housing type, home count and income tier:

    gap_monthly      = max(0, monthly_cost − ami_4person × target_pct × 0.30 / 12)
    subsidy_per_home = gap_monthly × 12 / annual_capital_cost_share

This is shown alongside any failed zoning rules and site flags.

## Grounded explanations

The model receives only computed metrics and the current weights, each metric
under an ID like `small_multi:affordability.ami_needed_pct`. The server rejects
the output, and falls back to a template, if any sentence:

- cites no metric ID;
- cites an ID that was not in the input;
- contains a number that does not appear in the input (after rounding).
