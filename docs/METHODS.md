# Methods

Two layers, kept apart on purpose:

- **Evidence** (`core/engine.py`) computes each metric per housing type with a
  range and a provenance. No weight ever enters it.
- **Values** (`web/src/lib/scoring.ts`, mirrored in `core/scoring.py`) combine
  the evidence using weights that the user controls.

Every number below comes from `data/config/assumptions.yaml`. Housing types come
from `typologies.yaml`, and criteria and their directions from `criteria.yaml`.

## Uncertainty ranges

Each assumption has `value`, `low` and `high`. The engine evaluates each formula
once at the central values, then 300 more times with every assumption drawn
uniformly from [low, high] (seeded, so results are stable). A metric reports
the central value plus the 5th–95th percentile of the draws.

**Provenance** is the weakest input. If any placeholder feeds a metric, the
metric is a placeholder. Otherwise the order runs modeled, then assumption, then
observed.

## Homes per lot (built form, not zoning)

For types with a fixed count (detached, duplex, house + ADU), the count is the
fixed number. Otherwise:

    homes = clamp(floor(lot_area / lot_sf_per_unit_for_form), units.min, units.max)

If the lot is smaller than `min_lot_sf_for_form`, the card says so.

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
| Adds displacement pressure | `homes × renter_cost_burden_share × (1 − min(1, tract_median_income / income_needed))` | lower better |
| Strain on infrastructure | `homes × (1 + Σ hazard weights present) × sewer_stress_index` | lower better |
| Households gaining job access | `homes × jobs_access_index` | higher better |
| Carbon per household (30 yr) | see below | lower better |

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
