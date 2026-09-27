# Tax in the evidence layer

Date: 2026-09-26 · Status: implemented 2026-09-26 (plan: `docs/superpowers/plans/2026-09-26-tax-metrics.md`)

## 1. Summary

Property tax is already in Lotline, invisibly. `operating_cost_per_unit_month` is
a flat placeholder of $450/unit/month whose rationale reads "Taxes, insurance,
maintenance, management, reserves." Every scenario on every lot pays the same
undifferentiated blob, so tax can never change a ranking and a user can never
see it.

This spec makes tax explicit in four places, adding exactly **one** new scored
criterion:

| Concern | Lands as | Scored |
|---|---|---|
| Public revenue the parcel yields | `revenue.public_horizon` — cumulative over the analysis horizon, net of abatement | **New criterion `public_revenue`** |
| Tax cost to the household | splits out of `operating_cost_per_unit_month`, feeds `affordability.ami_needed_pct` | No — corrects an existing input |
| Abatements | modulates the revenue series; stabilized figure in the receipt | No — feeds the criterion |
| This lot's tax status today | `site.tax_status_today`, `site.forgone_revenue` | No — site context |

Low-Income Housing Tax Credits are deliberately **out of scope**; see §11.

## 2. Why, and what this refuses to claim

A CDC project lead in predevelopment has to answer "what does the City get back"
before a council member or a community meeting asks it. Today Lotline cannot
answer it at all. The vacant lot in front of them pays almost nothing, and
returning land to the tax rolls is the Pittsburgh Land Bank's stated mission, so
the question is not exotic — it is the first one asked.

Public revenue is also the criterion on which the tool's audiences most visibly
disagree. City Planning and the URA weigh it; a long-time resident may weigh it
at zero. That disagreement is the product's signature interaction, and until now
no criterion carried it.

**What this explicitly does not claim.** New construction raising nearby
assessments — "tax pressure on neighbors" — is a causal displacement claim.
CLAUDE.md §0.1 forbids those, and no longitudinal method here supports one. It is
named in LIMITATIONS.md and appears in no metric.

## 3. What the data supports

Verified against the live WPRDC assessment resource
(`9a1c60bd-f9f7-4aba-aeb7-af8c3aaa44e5`) on 2026-09-26:

- Required fields all present: `TAXCODE`, `TAXDESC`, `ABATEMENTFLAG`,
  `HOMESTEADFLAG`, `FAIRMARKETBUILDING`, `COUNTY*`/`LOCAL*`, `YEARBLT`.
- `TAXDESC` vocabulary is `20 - Taxable`, `10 - Exempt`, `12 - PURTA`.
- Multi-unit buildings are classed `COMMERCIAL` with the unit band written into
  the use class: `APART: 5-19 UNITS`, `APART:20-39 UNITS`, `APART:40+ UNITS`.
  Per-home value is therefore derivable for `small_multi` and `midrise`.
- `datastore_search_sql` is blocked by the CDN (HTTP 403). The pipeline must use
  `datastore_search` with paging, not SQL aggregation.

**The finding that set the architecture.** Median assessed building value for
`SINGLE FAMILY` is about $71,800. Allegheny County assessments are base-year
(2012-equivalent) values, not current market prices. Estimating a new building's
assessed value from its development cost would therefore overstate it by roughly
a factor of two, in the same direction, on every scenario.

So assessed value comes from **observed comparables in the county's own data**,
never from development cost. This has two independent justifications and both
matter:

1. **Correctness.** Cost is a current-dollar number; assessment is a base-year
   number. They are not the same quantity.
2. **Independence.** A cost-derived revenue figure would be a near-exact positive
   multiple of `affordability.dev_cost_per_unit`. Two criteria that are the same
   number in different clothes cancel in the weighted sum, and only their weight
   difference does any work. That is precisely how the `opportunity` criterion
   failed on 2026-09-26. §9 turns this into an enforced test rather than a
   comment.

A corollary: comps must be restricted by `YEARBLT` to recent construction. A 1920
rowhouse's assessment is not evidence for what a new rowhouse would be assessed
at.

## 4. Architecture

One new module, `core/tax.py`. Pure evidence layer — no weight enters it, same
contract as `core/metrics.py`. It consumes a comps table built offline and
produces Metrics plus an annual revenue series.

```
pipeline/steps/assessment_comps.py
        |   median assessed value per home, by (typology x neighborhood),
        |   IQR as low/high, YEARBLT-restricted, comp count retained
        v
data/processed/assessment_comps.json          [provenance: observed]
        |
        v
core/tax.py
   assessed  = units x per_home_value + land_value
   annual    = assessed x (city + school + county millage)      <- tax.yaml
   abatement schedule applied to the early years of the horizon
        |
   |- revenue.public_horizon      cumulative, net of abatement   -> criterion
   |- revenue.annual_stabilized   after abatement expires        -> receipt, memo
   |- tax.per_home_monthly        -> affordability.ami_needed_pct
   |- site.tax_status_today,
      site.forgone_revenue                                       -> site context
```

`core/engine.py` calls into `core/tax.py` inside its existing per-typology loop
and merges the returned metrics into the scenario's `metrics` dict. The revenue
series reuses the `CarbonSeries` shape and the existing chart component.

## 5. Config

### 5.1 New: `data/config/tax.yaml`

Every number (millage per body, homestead exclusions, abatement years and cap) is
an `assumptions.yaml` entry referenced from `tax.yaml` by key, so it carries a
range, provenance and source and flows through `Samples`, `dependsOn`, inquiries
and the LIMITATIONS count. `tax.yaml` holds structure and legal terms; an
abatement program carries `reviewed: false` until a person verifies it.
"Reviewed" for a rate means its assumption is no longer a placeholder. Stand-in
values ship labeled STAND-IN by design — this is the intended initial state, not
an open question in this spec. The common level ratio is dropped: it converts
market to assessed value, and the comps are already assessed.

```yaml
millage:                      # one entry per taxing body
  - { id: city,   label: City of Pittsburgh,        value: null, source: ..., reviewed: false }
  - { id: school, label: Pittsburgh Public Schools, value: null, source: ..., reviewed: false }
  - { id: county, label: Allegheny County,          value: null, source: ..., reviewed: false }

homestead:
  exclusion_usd: { value: null, source: ..., reviewed: false }
  applies_to_tenure: [owner]

abatements:
  - id: ...
    label: ...
    eligible_use_keys: [...]        # matches typologies.yaml use_key
    years: null
    annual_exempt_cap_usd: null
    code_section: ...
    quote: ...
    confidence: ...
    reviewed: false

comps:
  min_comps: 30
  built_since_year: null            # set during review
  fallback: [neighborhood, citywide]
  use_classes:                      # USEDESC -> homes per comp parcel
    "SINGLE FAMILY":     { homes: 1 }
    "ROWHOUSE":          { homes: 1 }
    "TOWNHOUSE":         { homes: 1 }
    "TWO FAMILY":        { homes: 2 }
    "APART: 5-19 UNITS": { homes: 12, low: 5,  high: 19 }
    "APART:20-39 UNITS": { homes: 29, low: 20, high: 39 }
    "APART:40+ UNITS":   { homes: 60, low: 40, high: 120 }
```

Band midpoints are a modeling choice, not data. They carry `low`/`high` from the
band edges so the uncertainty flows through the existing `Samples` machinery. The
open-ended `40+` band has no upper edge in the source vocabulary; its `high` is a
documented cap, it is the weakest number in the feature, and it gets its own line
in LIMITATIONS.md.

### 5.2 Changed files

- **`typologies.yaml`** — each typology gains `assessment_use_classes: [...]`,
  a list of `USEDESC` values keying into `tax.yaml: comps.use_classes`.
- **`criteria.yaml`** — new criterion, and a new top-level `tension_flags` key
  (§7):
  ```yaml
  - id: public_revenue
    metric_id: revenue.public_horizon
    label: Public revenue over the horizon      # horizon templated from
                                                # assumptions.analysis_years,
                                                # never a literal in the label
    question: How much property tax would this option return to the City, the
              school district and the county?
    direction: higher_is_better
    group: fiscal                               # new group; `group` is a free string
    default_weight: 1
  ```
- **`stakeholders.yaml`** — config validation requires every profile to name
  exactly the criteria in `criteria.yaml`, so all seven profiles gain a weight.
  Intended spread: City Planning and URA high; CDC low; developer low (a
  developer weighs their own tax bill, which is the occupant/opex side, not the
  City's receipts); long-time resident and climate advocate near zero.
  Adding a seventh criterion dilutes the 100-point budget and shifts every
  preset's relative weights. That is expected.
- **`assumptions.yaml`** — `operating_cost_per_unit_month` drops taxes from both
  its value and its rationale; it becomes insurance, maintenance, management and
  reserves only. Its new value/low/high are set during the same review pass that
  fills `tax.yaml` and stay `provenance: placeholder` until sourced, exactly as
  today. Also gains `criterion_independence_max_corr` — the threshold used by
  test 1 in §9 — so the guardrail is a reviewable config value rather than a
  literal in a test.
- **`sources.yaml`** — new entries for the PA State Tax Equalization Board (CLR),
  the City millage ordinance, Pittsburgh Code Title Two, and the Allegheny County
  homestead program.
- **`core/config.py`** — pydantic models for `tax.yaml` and for `tension_flags`;
  validation fails loudly when a `tension_flag` names an unknown criterion id or
  a typology names an unknown use class.

## 6. Engine changes

**Revenue.** `assessed = units x per_home_value + land_value`, times the summed
millage, per year across `assumptions.analysis_years`, with abated years reduced
per the applicable program. Cumulative net of abatement is the criterion;
`revenue.annual_stabilized` (post-abatement steady state) is a full `Metric` with
its own range and provenance, not a bare number, and rides along for the receipt
and memo because that is the figure a resident or council member will quote.

**Household tax.** `tax.per_home_monthly` is computed from the same assessed
value and millage, with the homestead exclusion applied only to typologies whose
`tenure_default` appears in `tax.yaml: homestead.applies_to_tenure`. It replaces
the tax share of `operating_cost_per_unit_month` inside the monthly-cost chain.

This **changes numbers that exist today.** Per-home tax is lower for a midrise
(smaller, lower-value homes) than for a detached house, so affordability shifts
slightly toward density — a real effect currently hidden inside a flat
placeholder. `docs/METHODS.md` and any affected fixtures move with it.

**Site context.** `site.tax_status_today` from `TAXDESC` (observed);
`site.forgone_revenue` is what the parcel yields today, which for an exempt or
city-owned vacant lot is approximately nothing.

**Provenance.** A tax rule with `reviewed: false` yields
`provenance: placeholder`, hatched in the UI, with a range spanning the plausible
band — exactly how an unreviewed zoning district behaves today. An unreviewed
rule never produces a confident number and never excludes a scenario.

## 7. Tension flags

A rank on a single criterion involves no weights, so "ranks first on revenue and
last on affordability" is a statement about the ordering of two measured columns:
evidence, not values. It is therefore computed server-side in `core/engine.py`,
shipped in `Analysis`, and appears in the memo export.

```yaml
tension_flags:
  - id: revenue_vs_affordability
    label: High revenue, high exclusion
    top_on: public_revenue
    bottom_on: [affordability, local_affordability_gap]
    message: >-
      This option yields the most public revenue and is also the least
      affordable of the options compared. Both are true at once; which
      matters more is a values question, not an evidence one.
```

The engine iterates whatever `tension_flags` declares — first on X, last on any
of Y — so the mechanism generalizes (a later flag could pair build cost against
carbon) without code changes. The sentence is deterministic config text, which
keeps it inside the rule that the ranking must be legible without AI prose.

## 8. Human review of tax law

New `pipeline/tax/rules_review.yaml`, mirroring `pipeline/zoning/rules_review.yaml`.
Millage rates, the common level ratio, the homestead exclusion and each abatement
program carry a citation, a short quote, a confidence, and `reviewed: false`
until a teammate verifies them against the ordinance and the published rate.

This extends the existing human-in-the-loop story rather than inventing a second
one: the model's recollection of tax law is treated exactly like its recollection
of the Zoning Code — as a draft for a human to check, never as an input to a
ranking.

## 9. Tests

1. **Independence.** Sample parcels across the city; for each, normalize every
   criterion column across that lot's scenarios and fail if `public_revenue`'s
   column correlates with any other criterion's past
   `assumptions.criterion_independence_max_corr`. Run per lot, not pooled: the
   `opportunity` failure was a within-lot cancellation, and pooling across lots
   would hide it. The threshold is 0.999: an affine restatement gives |r| = 1 to
   machine precision, while two criteria that merely share home count as a
   driver land near 0.99 on lots where one option is far denser than the rest —
   a fact about the lot, not a defect.
2. **Unreviewed rule.** A tax rule with `reviewed: false` produces
   `provenance: placeholder` and a band spanning the plausible range.
3. **Comps fallback.** A neighborhood below `min_comps` falls back to citywide
   and says so in the metric note.
4. **Abatement arithmetic.** Cumulative net revenue is below cumulative gross by
   exactly the abated amount; a zero-year abatement leaves them equal.
5. **Exempt parcel.** A `10 - Exempt` parcel returns a complete analysis with
   `site.forgone_revenue` at approximately zero, and does not crash.
6. **Nothing enumerated in code.** The existing synthetic fixture gains fake
   typologies with fake use classes and a fake abatement program, and still
   produces a complete analysis.

## 10. Docs

- `METHODS.md` — the tax section, with formulas, in plain language.
- `LIMITATIONS.md` — base-year assessment caveat; comps are existing buildings,
  not new ones; the open-ended `40+` band cap; assessment appeals not modeled;
  reassessment spillover explicitly not claimed; LIHTC absent; count of
  unreviewed tax rules appended automatically alongside the zoning count.
- `SOURCES.md` — regenerated from `sources.yaml`.
- `AI_DISCLOSURE.md` — tax rules drafted with LLM assistance and human-reviewed,
  same as zoning.
- `README.md` — LIHTC named as a next step.

## 11. Out of scope

- **LIHTC.** A competitive state allocation under PHFA's QAP. A number we cannot
  defend is worse than an absence we can name. Recorded as a next step.
- **Reassessment spillover onto neighbors.** A causal displacement claim;
  forbidden by CLAUDE.md §0.1.
- **Assessment appeals**, which in Allegheny County materially move real assessed
  values. Named in LIMITATIONS.md.
- **Municipalities outside the City of Pittsburgh**, which have their own millage
  and their own abatement programs.

## 12. Risks

| Risk | Handling |
|---|---|
| Comps are older buildings; a new build is assessed differently | `YEARBLT` restriction; IQR as the range; provenance observed but noted |
| Thin neighborhood samples | `min_comps` with citywide fallback, announced in the metric note |
| Revenue duplicates an existing criterion | Enforced by test 1, not by argument |
| Unreviewed millage silently ranks scenarios | Placeholder provenance and a spanning band until `reviewed: true` |
| Revenue criterion read as "build the expensive thing" | Tension flag (§7), honest preset spread, and a criterion any user can zero |
| Splitting tax out of opex changes today's outputs | Intended; METHODS.md and fixtures updated in the same change |
