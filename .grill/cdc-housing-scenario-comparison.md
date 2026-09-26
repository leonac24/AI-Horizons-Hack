# Grill: CDC housing scenario comparison
Date: 2026-09-26

## Intent
Build Lotline as an early-predevelopment decision-support tool for a community development corporation. After the CDC identifies a real vacant parcel but before it pays for detailed design, the tool helps it decide which housing concepts deserve further architect, lender, and community review. Lotline presents evidence and tradeoffs; the CDC supplements that evidence with local knowledge and makes the final decision.

The core demo lets a CDC user select a real city-owned vacant parcel, define priorities, compare up to three housing scenarios, see why they ranked differently, and distinguish data-driven conclusions from value judgments.

## Constraints
- Roughly a day and a half remains for the hackathon build.
- The tool provides decision support, not zoning, legal, engineering, financial, market, or community-preference advice.
- The first version may use explicit unknowns and placeholders, but it must never invent unavailable data or silently substitute proximity for capacity.
- The citywide map may have uneven data completeness. A geographically varied sample must support the complete comparison workflow, while all other parcels must degrade without crashing.
- Featured demo parcels are city-owned vacant land. Other vacant parcels may appear when ownership and availability uncertainty are clearly distinguished.
- Evidence calculations and rankings are deterministic and inspectable. AI may extract candidate zoning rules for human review and translate computed results into prose, but it cannot invent inputs, alter scores, resolve missing evidence, or choose a scenario.
- Scenario comparisons are capped at three.

## Key decisions
- Decision: Design first for a CDC project lead during early predevelopment. Reason: this gives the product one concrete workflow and decision owner. Alternative considered: simultaneously designing for planners, developers, residents, and public officials.
- Decision: Make a parcel-specific compatibility claim rather than claiming to determine what a neighborhood needs. Reason: neighborhood indicators cannot replace CDC local knowledge or community input. Alternative considered: inferring neighborhood housing demand and prescribing the needed typology.
- Decision: Define demand as documented household need and fit using household composition, income tiers, tenure, cost burden, and suitable housing-plan or waiting-list evidence. Reason: these inputs support a need claim. Alternative considered: claiming market absorption or community preference.
- Decision: Compare demand, physical feasibility, affordability, displacement risk, infrastructure capacity, access to opportunity, and marginal carbon emissions. Reason: these are the minimum top-level decision categories selected for the product.
- Decision: Treat physical feasibility as screening only. Reason: parcel geometry, zoning dimensions, slope, access, and hazards can support a plausible unit range but not a buildable design. Alternative considered: generating a conceptual site plan.
- Decision: Keep resident affordability and CDC project feasibility separate. Reason: household affordability and the funding gap answer different questions and should not cancel each other inside one metric.
- Decision: Define the eventual displacement outcome as incremental involuntary moves by nearby households attributable to a scenario relative to a no-project baseline. Reason: this is the decision-relevant causal quantity. Alternative considered: counting all nearby moves. The first version will report direct displacement when supported and otherwise show vulnerability and pressure indicators rather than inventing a causal household count.
- Decision: Use a two-tier infrastructure contract. Reason: public data rarely proves true spare capacity. Required coverage is sewer/stormwater, water, street and emergency access, transit, power-service availability, schools, parks, healthcare, groceries, and broadband; additional CDC evidence appears separately. Missing measures remain explicitly unknown.
- Decision: Disaggregate access to opportunity by destination category and score walking, biking, and public transit. Reason: a single composite can hide who and what benefits. Driving may be shown as optional context with zero default weight.
- Decision: Assess whole-life carbon over a 60-year reference study period. Report total kgCO2e, kgCO2e per square meter, and kgCO2e per dwelling. Reason: 60 years follows established whole-life carbon practice for domestic projects, while per dwelling matches a measurable physical unit. Alternatives considered: 30 years, per person, per household, and per household-year.
- Decision: Require the CDC user to allocate a 100-point budget across the seven top-level categories before ranking. Reason: there is no neutral default weighting, and the allocation forces explicit tradeoffs. Submetrics remain visible and use transparent config-defined equal weights by default, with optional advanced adjustment.
- Decision: Separate hard requirements from normative weights. Reason: weighted compensation must not make an illegal scenario appear qualifying. Verified applicable legal requirements are mandatory; strong federal, Pennsylvania, or Pittsburgh agency recommendations are cited, overrideable warnings with ranking penalties; interpretation-dependent items require professional review.
- Decision: Define a scenario as housing form, estimated unit count and unit-size mix, tenure, target affordability mix, parking, and major construction assumptions. Reason: typology names alone omit the choices driving the metrics. Lotline may generate editable starting scenarios.
- Decision: Always name a provisional first-ranked scenario, even with missing evidence. Reason: the user wants an ordered result. The interface must show excluded criteria, unsupported weight, nearby warnings, and ranking uncertainty.
- Decision: Show a midpoint-weighted ranking plus rank robustness across plausible sampled outcomes. Reason: the CDC can see both the ordered result and how often uncertainty reverses it.
- Decision: Explain rankings with an auditable receipt separating evidence, values, score contribution, and uncertainty. Reason: users should not need AI prose to understand the result. Natural-language AI explanation is optional polish.
- Decision: Defer work-backwards analysis, advocate/referee calls, full memo export, and sophisticated commute routing until the core comparison is reliable. Reason: source validity and the end-to-end comparison take priority. Alternative considered: broad feature completeness for the demo.

## Surfaced assumptions
- Publicly available indicators can support neighborhood need and vulnerability screening, but not a causal estimate of nearby displacement without suitable longitudinal data and validation.
- Proximity to infrastructure or services is not evidence of available capacity.
- Unit count and parcel fit will be approximate until professional site, survey, utility, geotechnical, and code review.
- Dwelling count is measurable at concept stage; future household turnover and occupancy are not.
- Equal submetric weights are still a value choice, so they must be visible and configurable rather than described as neutral.
- A first-place label can coexist with uncertainty if it is explicitly provisional and accompanied by robustness information.

## Open questions
- Which current datasets, fields, licenses, vintages, and geographic joins can support each required metric?
- Which Pittsburgh legal requirements can be evaluated automatically at concept stage, and which require planner or professional interpretation?
- Which federal, Pennsylvania, and Pittsburgh agency recommendations are strong enough to include as default warning thresholds?
- What validated longitudinal evidence, geographic radius, and time horizon would be needed for a future causal displacement estimate?
- Which city-owned vacant parcels provide the strongest geographically varied demo and test sample?
- Which three editable scenarios should be generated for the featured parcel?
- What project-cost, unit-size, construction, grid-decarbonization, and transportation assumptions can be sourced defensibly within the remaining time?

## Out of scope
- Recommending what a neighborhood needs or what must be built.
- Predicting market absorption or claiming community preference without project-specific evidence.
- Producing a buildable site plan or replacing architects, engineers, utilities, planners, lenders, attorneys, or community engagement.
- Treating voluntary guidance as law.
- Claiming confirmed utility, school, grid, or service capacity from proximity data.
- Estimating scenario-caused nearby household displacement without a validated causal method.
- Using driving access to improve the default opportunity ranking.
- Requiring AI-generated prose to understand or verify the ranking.
