# CLAUDE.md: Pittsburgh Housing Typology, Equity & Climate Matchmaker

AI Horizons 2026 · AI for Housing Hackathon · Challenge 03
Working name: **Lotline** (rename in `data/config/app.yaml`).

---

## 0. What this is

A decision-support tool for vacant land in **the City of Pittsburgh**. Pick any
vacant lot in the city and compare what could be built there: who each option
houses, what it costs, what it emits, what the zoning allows, and how the ranking
changes depending on whose priorities you use.

**Primary user:** a community development corporation (CDC) project lead in early
predevelopment. They have a real parcel in mind and must decide which housing
concepts deserve architect, lender, and community review before paying for
design. Lotline presents evidence and tradeoffs; the CDC adds local knowledge and
makes the decision. **Secondary audiences:** City Planning, the URA, and residents
who want to see the tradeoffs and value judgments behind a proposal.

It is built for Pittsburgh's actual conditions: hillside lots and landslide risk,
combined sewer overflows, a large inventory of vacant and publicly held land,
transit that follows the valleys and busways, and neighborhoods where new
investment and displacement pressure sit side by side. Those are first-class
features, not generic add-ons.

**Positioning (mandatory):** decision support only. Not zoning, legal, or
financial advice. Persistent banner: "Confirm with City of Pittsburgh Department
of City Planning."

**Core principle: evidence and values are separate layers.** The evidence layer
computes metrics with ranges and provenance. The values layer (weights) is
user-controlled. No weight ever enters an evidence metric.

**Hard requirements come before weights.** A scenario that fails a verified legal
requirement (e.g., the use is prohibited in the district) is excluded from ranking,
not scored low — no weighting can make an illegal option rank first. Excluded
scenarios are still shown, with the citation. Unreviewed rules never exclude
anything; they show "Needs planner review."

---

## 0.1 Product decisions

The grill session in `.grill/cdc-housing-scenario-comparison.md` is the record of
*why*. Outcomes that bind the build:

- **Compatibility, not prescription.** Lotline says how well options fit a parcel;
  it never says what a neighborhood needs or what must be built.
- **Physical feasibility is screening only** — a plausible unit range, not a
  buildable design.
- **Resident affordability and project feasibility stay separate** metrics; they
  answer different questions and must not cancel inside one number.
- **No causal displacement claim.** Report the share of new homes priced above
  what nearby renters can pay, plus vulnerability context — never a count of
  households displaced.
- **Proximity is not capacity.** Being near a sewer, school, or stop is not
  evidence of spare capacity; unmeasured capacity stays explicitly unknown.
- **Always name a provisional first place**, shown with its robustness (SMAA),
  excluded criteria, and unsupported weight.
- **The ranking must be understandable without AI prose.** The tradeoff receipt
  is the explanation; generated text is an optional layer on top.

---

## 1. Scope: the whole city, no favorites

- Every vacant parcel inside City of Pittsburgh limits is selectable and analyzable.
- Neighborhoods (the city's official neighborhood boundaries) are for **navigation and filtering** — search, zoom, compare — never the limit of what works.
- "Suggested lots" are auto-picked to spread across the city (different neighborhoods, zoning districts, slope, flood exposure). They are starting points, not the demo's boundary.
- Outside city limits is out of scope. Allegheny County's other municipalities each have their own zoning code; name this in LIMITATIONS.md.

---

## 2. Config over literals

Pittsburgh-specific facts live in `data/config/`, not scattered through code. This
keeps the Pittsburgh content reviewable in one place and means extending later
(another municipality) is a data job, not a rewrite.

Never in code: parcel/tract/neighborhood IDs or names, zoning district codes,
typology lists (`if typology == "duplex"`), cost/carbon/AMI numbers, colors or
labels per typology. Code iterates over whatever config declares.

| File | Declares |
|---|---|
| `app.yaml` | Name, tagline, disclaimer text |
| `city.yaml` | Pittsburgh: boundary source, neighborhood layer, parcel filters, suggested-lots rule, source overrides |
| `zoning.yaml` | Pittsburgh Zoning Code (Title Nine) location, district layer, citation format, extraction targets |
| `typologies.yaml` | Housing types — id, label, unit range, form params, color |
| `criteria.yaml` | Criteria — id, label, direction, group, default weight |
| `households.yaml` | Illustrative Pittsburgh households — income as % of Pittsburgh-area AMI, size, tenure, where they commute |
| `stakeholders.yaml` | Preset weight profiles (long-time resident, CDC, developer, City Planning, URA…) |
| `assumptions.yaml` | Every number with `value`, `low`, `high`, `unit`, `source`, `rationale` (Pittsburgh construction costs, PA energy mix, PRT service assumptions) |
| `sources.yaml` | Dataset registry: id, name, publisher, url, vintage, license |

All config validated by pydantic at startup; fail loudly with clear messages.
Frontend reads the same config (served as JSON) to build labels, legends, sliders,
and chart series.

---

## 3. Hard rules (hackathon compliance)

1. **No pre-existing code.** Public libraries fine (list in README).
2. **Commit often**, descriptive messages, history intact. Never force-push or squash main.
3. **No secrets in the repo.** `.env` gitignored; ship `.env.example`. Check `git diff --staged` before every commit.
4. **No PII.** Drop owner-name fields in the parcel adapter. Households are synthetic and labeled "illustrative".
5. **Never invent data.** Unavailable → `provenance: "placeholder"`, visibly labeled.
6. **Repo public** at submission and after.

---

## 4. Stack

- **Python:** 3.14 managed by `uv` (`uv sync`, `uv run ...`). Runtime deps in `[project]`; GeoPandas etc. only in the `pipeline` dependency group so the deployed function stays small.
- **Pipeline:** pandas, GeoPandas, shapely, numpy, pydantic, PyYAML. `pipeline/`. Runs locally, never deployed.
- **Shared engine:** `core/` — config loading, metrics, zoning evaluation, scoring/SMAA mirror. Imported by pipeline, server, and tests.
- **Backend:** FastAPI (`server/`) — serves data, computes per-parcel metrics on demand, proxies LLM calls. No GeoPandas at runtime.
- **Frontend:** Vite + React + TypeScript (strict), MapLibre GL JS (OpenFreeMap basemap, no key), Recharts. `web/`.
- **LLM:** provider interface in `server/llm.py`; provider from env `LLM_PROVIDER` (`gemini` | `none`). Gemini free tier via `google-genai`; models from `LLM_MODEL` (runtime) and `ZONING_EXTRACT_MODEL` (offline). `none` → deterministic templates.
- **SMAA:** TypeScript in the browser for live updates; mirrored in Python for tests.
- **Hosting:** Vercel. Static web build + `api/index.py` (FastAPI) as a Python function; `/api/*` rewritten to it. Parcel points are a static file on the CDN (`web/public/data/`).

Ask before adding any large dependency not listed here.

```
/pipeline/adapters   # one module per source type
/pipeline/steps      # generic processing steps
/pipeline/zoning     # LLM extraction, prompts, human-review file
/data/raw            # gitignored if large; fetch steps in docs/SOURCES.md
/data/processed      # parcel index and derived data the app reads
/data/config         # all Pittsburgh facts and knobs
/core                # shared engine (config, metrics, zoning, scoring)
/api                 # Vercel function entry
/server  /web  /docs
```

---

## 5. Pittsburgh data sources

Check the hackathon's published Data Resources list first — organizers may have
cleaned versions. **Verify every URL and field name**; record each in
`sources.yaml` and `docs/SOURCES.md`. Do not rely on remembered URLs.

| Need | Source |
|---|---|
| Parcels, land use, assessed value, ownership type | Allegheny County Property Assessments + parcel boundaries (WPRDC) |
| Publicly held / land bank status | City-owned property and Pittsburgh Land Bank inventory (WPRDC / city) |
| Zoning districts | City of Pittsburgh zoning layer (WPRDC) |
| Zoning rules | Pittsburgh Code of Ordinances, Title Nine (Zoning Code) |
| Neighborhood boundaries | City of Pittsburgh neighborhoods layer (WPRDC) |
| Housing need, cost burden | HUD CHAS (tract) |
| Demographics, rents, incomes | ACS 5-year (tract / block group) |
| Income limits / AMI | HUD income limits for the Pittsburgh metro area |
| Transit | Pittsburgh Regional Transit (PRT) GTFS |
| Jobs | Census LODES (Pennsylvania) |
| Flood | FEMA NFHL |
| Slope / landslides | City steep-slope and landslide-prone layers, county DEM |
| Sewer | ALCOSAN / PWSA combined-sewer and CSO data |
| Development activity | City of Pittsburgh building permits (WPRDC) |
| Travel cost, walkability | EPA Smart Location Database |

Adapters share one interface (`fetch(config)`, `describe()`), take locations from
config, drop PII, return provenance, and degrade to placeholders instead of
crashing.

---

## 6. Working at city scale

Too many parcels to precompute everything, so split the work:

- **Pipeline (every parcel in the city):** compact index with id, simplified geometry, lot area, vacancy, public/land bank ownership flag, zoning district, neighborhood, tract/block group (spatial join), flood flag, slope class, sewer/CSO flag, transit access cell.
- **Server (per clicked parcel):** zoning check for each typology, affordability, households, commute, carbon, scoring inputs. Cache by `(parcel_id, config_hash)`. Target < 1.5 s click to full view.
- **Browser:** SMAA, weights, ranking flip.
- **Map:** load parcels by viewport from the server; centroids when zoomed out, polygons when zoomed in. PMTiles fine if tippecanoe installs easily — ask first.
- **Commute (deferred until the core comparison is solid):** precompute a PRT travel-time matrix from access cells (block groups or grid) to destination types; add each parcel's walk-to-stop leg with a slope penalty. Pittsburgh's hills make a straight-line walk estimate misleading.
- **Zoning:** extract rules for every district in the Zoning Code that permits any residential use. Review first the districts containing the most vacant parcels. A lot whose district isn't reviewed still loads, flagged "Needs planner review."

---

## 7. Evidence layer

```ts
type Provenance = "observed" | "modeled" | "assumption" | "placeholder";

interface Metric {
  id: string;          // from criteria.yaml, e.g. "affordability.share_lowest_tier_housed"
  label: string;       // plain language
  value: number;
  low: number;
  high: number;
  unit: string;
  provenance: Provenance;
  sourceIds: string[]; // keys into sources.yaml
  note?: string;
}
```

Zoning statuses in `zoning.yaml` carry a semantic `role` (`permitted`,
`discretionary`, `variance`, `prohibited`, `unreviewed`). Code asks for a role,
never a status id.

Visual code: **solid** = observed · **dashed** = modeled · **outlined** =
assumption · **hatched + tag** = placeholder. Weights and stakeholder profiles use a
separate accent color and never appear inside metric displays.

---

## 8. AI components (substantive, not a wrapper)

**Zoning extraction (offline).** From Title Nine, extract per-district rules:
permitted status per typology (by-right / special exception / conditional use /
not permitted), minimum lot area, lot area per unit, height, setbacks, parking,
and any overlay or bonus provisions relevant to housing. Every rule carries
`code_section`, a short `quote` (< 25 words), and `confidence`. Validate against
JSON Schema. Output to `pipeline/zoning/rules_review.yaml`; **a teammate reviews
each rule and sets `reviewed: true`.** This is the human-in-the-loop story — say so
in the README and video.

**Grounded explanations (runtime).** Input is only the computed metrics + current
weights. Every sentence cites metric IDs, shown as chips. Server rejects sentences
citing unknown IDs or numbers not in the input, falling back to a template. Frame
as tradeoffs, never "you should build."

**Deferred: advocates + referee.** Two calls argue for scenario A vs. B; a third
labels each claim data-backed / value-dependent / unsupported. Not before the core
comparison is reliable.

---

## 9. Computations

- **Affordability:** rent/price needed to cover development cost per typology (Pittsburgh cost assumptions with ranges), compared against Pittsburgh-area income tiers.
- **Households:** each illustrative household checked against each scenario ("Could this household afford it?").
- **Commute (deferred):** from §6, to the household's destination type (e.g., Downtown, Oakland hospitals and universities).
- **Local affordability gap:** share of a scenario's homes priced above what nearby renters can pay (tract income and rents). Not a displacement count.
- **Access to opportunity:** site context, not a scored criterion, while it is a single lot-level index (it only scales with unit count and cancels against infrastructure load). When scored later, disaggregate by destination category and by walking, biking, and transit; driving is optional context with zero default weight.
- **Carbon over time:** whole-life, **60-year** reference period (horizon in `assumptions.yaml`, never in labels). Embodied (year 0) + operational (PA grid mix, decarbonizing) + transportation. Report **per dwelling and per m²**; mark crossover years between scenarios. *(Code currently uses 30 years per household — migrate.)*
- **Site constraints:** slope, landslide, flood, and CSO flags feed cost ranges and infrastructure notes; they never silently drop a scenario.
- **Scoring:** drop scenarios that fail a hard requirement; normalize each remaining criterion 0–1 across scenarios, respecting direction; weighted sum.
- **SMAA:** N weight vectors (N from config) from a seeded Dirichlet, uniform or centered on a stakeholder profile; metric values sampled within [low, high]. Rank-acceptability indices; < 200 ms in browser.
- **Ranking flip:** smallest single-weight change that swaps two scenarios, as a sentence.
- **Work backwards:** for a target typology and unit count, list each failed zoning rule (→ variance / special exception, with Title Nine citation), per-unit subsidy gap, and infrastructure flags.

Tests: config validation; direction-aware normalization; SMAA indices sum to 1;
ranking flip on a toy example; zoning rule evaluation; a **coverage test** that
samples random vacant parcels across the city and asserts each returns a complete
response (placeholders OK, crashes not); and a small synthetic fixture with fake
typologies proving nothing is enumerated in code.

---

## 10. UI

Plain language ("Could this household afford it?"). Warm civic-document
aesthetic — planning report, brick, hillsides, river light — not a dark dashboard.

1. **Pick a lot** — citywide map, vacant lots highlighted. Address / parcel ID search, jump to neighborhood, filters (size, zoning, publicly held, flood, slope, transit access), suggested lots.
2. **Compare** — all typologies from config by default; the user can pin **up to 3** for side-by-side comparison. Scenario cards with tradeoff receipt, household rows, carbon line, zoning status with citations; SMAA bars; ranking-flip sentence; optional grounded explanation. *(Next: editable scenarios — tenure, affordability mix, parking.)*
   - **Weights are a 100-point budget** across the criteria, always summing to 100. Stakeholder presets are ways to fill the budget. **No ranking is shown until the user picks a preset or moves a point** — there is no neutral default.
3. **Work backwards** — target → what would have to change.
4. **What we don't know** — placeholders, unreviewed districts, data gaps. Linked from every screen.
5. **Memo export** — one printable page for a community meeting or City Planning conversation.

**Signature interaction:** move the weights, watch stakeholder rankings shift.

---

## 11. Required docs

- `README.md` — what it does, who in Pittsburgh it's for, how to run, stack, team, next steps, pilot partners (a Pittsburgh CDC, City Planning, URA, Pittsburgh Land Bank).
- `docs/SOURCES.md` — generated from `sources.yaml`.
- `docs/METHODS.md` — each computation in plain language + formulas.
- `docs/LIMITATIONS.md` — **required.** What it gets wrong, who could be harmed by misuse, data gaps, what we don't claim. Auto-append placeholder counts, unreviewed districts, and the share of vacant parcels covered by reviewed rules. City limits only.
- `docs/AI_DISCLOSURE.md` — AI used to build it and AI inside it, with how outputs are checked.
- `docs/BACKEND.md` — API principles: public read-only API, the evidence boundary, idempotency and ETags, input limits from config (enforced by tests), security posture. Change a rule there, say so in the commit.

---

## 12. How to work here (for Claude Code)

- State a short plan before multi-file changes.
- About to type a Pittsburgh fact, ID, number, typology, color, or label into code? Put it in config instead; mention any literal you couldn't avoid.
- Keep the app runnable at every commit. Small vertical slices.
- Source slow or blocked? Use the placeholder path, label it, tell the team.
- API limits, parcel-id format, and route bounds come from config (`app.yaml: api.*`, `city.yaml: parcels.id_*`); the client is never the source of truth for any number.
- Tests and lint before committing. Messages: `area: what changed`.
