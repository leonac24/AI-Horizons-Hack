# Lotline

**Pittsburgh Housing Typology, Equity & Climate Matchmaker.**
AI for Housing Hackathon (AI Horizons 2026, Pittsburgh). **Track: Challenge 3:
Housing Typology, Equity & Climate Matchmaker.**

| | |
|---|---|
| **Demo video (3–5 min)** | _TODO: add the public link_ |
| **Live app** | https://lotline-pgh.vercel.app |
| **Repository** | https://github.com/leonac24/LotLine |

> **Decision support only.** Lotline is not zoning, legal, or financial advice.
> Confirm anything consequential with the City of Pittsburgh Department of City
> Planning.

## The problem

A community development corporation (CDC) with a vacant lot in mind has to
decide which housing concepts are worth paying an architect, a lender and a
community process to look at. Today that first screen means reading Title Nine
district by district and pulling parcel, hazard, income and cost data from a
dozen places. Even then, the options pull against each other: more homes, deeper
affordability, lower carbon, less site risk. A tool that names one right answer
hides the tradeoff. Lotline shows what each option gives up and how the ranking
depends on whose priorities you use.

## Who it's for

- **CDC project leads** in early predevelopment, choosing which concepts to take
  into design review. This is the primary user.
- **City Planning and the URA**, weighing options for publicly held land.
- **Residents** who want to see the tradeoffs, and the value judgments, behind a
  proposal.

## What it does

Pick any of the **22,183 vacant lots in the City of Pittsburgh** (from county
assessment records). Lotline compares six housing types from
`data/config/typologies.yaml` (detached house through midrise) by:

- who each one houses and what it costs;
- what it emits over 30 years;
- what the Zoning Code allows;
- how the ranking changes depending on whose priorities you use.

The workflow:

1. **Pick a lot.** A stylized 3D model of Pittsburgh on real terrain, with every
   vacant parcel at its real location. Search by address or parcel ID, describe
   the lot you want in plain English, filter by size, zoning, public ownership
   or site hazard, or start from suggested lots spread across the city.
2. **Build on it.** Drag housing types onto the lot. The pad uses the lot's real
   frontage and depth from the deed legal description where available.
   Buildings that are off the lot, overlapping, or prohibited by zoning turn red.
   Every change re-evaluates "Your plan" on the server.
3. **Compare.** Your plan next to each housing type: zoning status with Title
   Nine citations, "Could this household afford it?" for illustrative
   households, carbon over time with crossover years, and site flags (slope,
   landslide, undermining, flood, combined sewer).
4. **Whose priorities?** A 100-point weight budget and stakeholder presets
   (long-time resident, CDC, developer, City Planning, URA, climate). SMAA bars
   show how often each option ranks first once weights and uncertainty are
   sampled. A one-line "ranking flip" gives the smallest weight change that
   swaps the top two.
5. **Work backwards.** Pick a housing type, a home count and an income tier. See
   the zoning rules that fail (with the variance or special exception path),
   the subsidy gap per home, and the site flags.
6. **What we don't know.** Every placeholder, unconnected source and unreviewed
   zoning district, plus citywide coverage counts.
7. **Memo.** One printable page for a community meeting or a City Planning
   conversation.

**Evidence and values are separate.** Every metric carries a range, a
provenance and its sources: solid = observed, dashed = modeled, outlined =
assumption, hatched = placeholder. Weights are shown in their own color and
never enter a metric. An option that fails a verified zoning requirement is
excluded from the ranking, not scored low, and is still shown with its
citation.

## What works and what is a placeholder

**Working, on real data:**

- Citywide vacant-parcel index (22,183 lots) with zoning district,
  neighborhood, tract, public ownership, and site hazard flags.
- Zoning rules for 7 of 41 base districts, covering 88.1% of vacant parcels.
  Each rule cites its section and quotes the code verbatim.
- HUD FY2026 Pittsburgh income limits; 2024 ACS tract median income and renter
  cost burden (about 22,100 lots matched).
- FEMA flood, PWSA combined-sewershed, steep-slope, landslide-prone and
  undermined-area screens.
- Scoring, SMAA, ranking flip, work backwards, grounded AI explanations, memo.

**Placeholder or missing (labelled in the app):**

- 14 assumptions or fallbacks remain, including construction and operating
  cost, embodied and operational carbon, grid decarbonization, household VMT
  and sewer stress. Transit access is joined for 15,553 parcels, with a
  fallback for unmatched block groups. The app hatches placeholder-dependent
  values.
- EPA Smart Location transit access is a 2021 snapshot, not current route-level
  commute time. Current PRT GTFS, HUD CHAS and ResStock remain unconnected.
- Zoning overlays (Riverfront, IPOD, historic) and 34 smaller base districts
  have no rules. Those lots show "Needs planner review".

The current counts are generated into [docs/LIMITATIONS.md](docs/LIMITATIONS.md)
by `uv run python -m pipeline.docs`.

## Who benefits, who could be harmed, what we don't claim

- **Benefits:** CDCs get a first screen of a lot in one place, and
  residents get to see the value judgments behind a proposal rather than just
  its conclusion.
- **Could be harmed by misuse:** residents, if a ranking is used to skip
  community process (it is only the arithmetic result of the chosen weights);
  owners of privately held lots, if "vacant" is read as "available";
  low-income households, if an affordability "Yes" is read as an eligibility or
  pricing determination.
- **We don't claim:** that any lot can be built on or any option is permitted;
  a count of households displaced (we report the share of new homes priced
  above what nearby renters can pay); that being near a sewer, stop or school
  means spare capacity; that presets reflect what real organizations want; or
  that the AI adds facts.

Full statement: [docs/LIMITATIONS.md](docs/LIMITATIONS.md).

## Data and AI integrity

- **Sources are cited per metric.** Every dataset is registered in
  `data/config/sources.yaml` with publisher, URL, vintage, license and the date
  we verified it. Every number in `data/config/assumptions.yaml` carries a
  value, a low–high range, a unit, a source and a rationale.
- **No PII.** Owner names and mailing addresses are never fetched. Households
  are synthetic and labelled "illustrative". Only public data is sent to the
  Claude API.
- **No secrets in the repo.** `.env` is gitignored; `.env.example` ships
  instead.
- **Human-in-the-loop path for zoning.** Rules are extracted by AI from saved
  Title Nine text, and the build refuses any rule whose quote is not found
  verbatim in that text. Rules that pass are in force and every answer says
  "AI-extracted from Title Nine with a verbatim quote; not checked by a
  planner". A planner confirms rules in `pipeline/zoning/REVIEW.md`, which drops
  the label. Setting `require_human_review: true` in `data/config/zoning.yaml`
  makes only human-confirmed rules count. A persistent banner sends every user
  to City Planning.
- **Uncertainty is carried, not hidden.** Metrics have ranges, SMAA samples
  within them, and the ranking is always shown with its robustness.

## Data sources used

All are public. Full registry, licenses and verification dates:
[docs/SOURCES.md](docs/SOURCES.md).

| Dataset | Where we got it |
|---|---|
| Allegheny County Property Assessments | WPRDC (CKAN API) |
| Parcel Centroids with Geographic Identifiers | WPRDC |
| Allegheny County Parcel Boundaries | Allegheny County GIS (ArcGIS REST) |
| City-Owned Properties | City of Pittsburgh via WPRDC |
| Pittsburgh Zoning Districts | City of Pittsburgh via WPRDC |
| Pittsburgh Code of Ordinances, Title Nine (Zoning Code) | eCode360 (saved text snapshots in `data/sources/zoning/`) |
| Pittsburgh Neighborhoods | City of Pittsburgh via WPRDC |
| 25% or Greater Slope, Landslide Prone Areas, Undermined Areas | City of Pittsburgh via WPRDC |
| Street Centerlines | City of Pittsburgh via WPRDC |
| PWSA Combined Sewersheds | PWSA via WPRDC |
| FEMA National Flood Hazard Layer (Pennsylvania) | FEMA via PASDA |
| HUD FY2026 Income Limits (Pittsburgh HMFA) | HUD User |
| HUD 2024 Total Development Cost limits | HUD |
| 2024 ACS 5-Year Detailed Tables (B19013, B25070) | U.S. Census Bureau summary files |
| EPA Smart Location Database 3.0 transit access | U.S. EPA (ArcGIS REST) |
| EPA passenger-vehicle emissions factor | U.S. EPA |
| EPA eGRID2023 | U.S. EPA |
| Terrain Tiles (for the 3D city only; never in a metric) | AWS Open Data |

## AI tool disclosure

**Used to build Lotline:**

- **Claude Code (Anthropic)** wrote most of the first-pass code and docs with
  the team: pipeline, engine, API, frontend and tests. A person on the team
  decided each design question. Claude Code also hand-extracted the current
  zoning facts from Title Nine and checked the dataset endpoints.
- **GitHub Copilot coding agent** authored a few commits exclusively for fixing merge conflicts.

**Inside Lotline:**

| Where | Model | Guardrail |
|---|---|---|
| Zoning extraction (offline) | Claude API | JSON schema from config; every rule must quote the code verbatim or it is dropped |
| Tradeoff explanations and "Ask about this lot" (runtime) | Claude API | Every sentence must cite input metric IDs and use only input numbers, or the server falls back to a template |
| Plain-English lot search (runtime) | Claude API | Model can only choose from real filter values; code, not the model, finds lots |
| Source passage classification (offline) | Laya (local) | Labels are leads for review only; they cannot change metrics, zoning or rankings |

AI never sets a weight, changes a metric, or ranks options. With
`LLM_PROVIDER=none` the app runs with no AI at runtime. Details:
[docs/AI_DISCLOSURE.md](docs/AI_DISCLOSURE.md).

## Libraries, frameworks and APIs

- **Python runtime (deployed):** FastAPI, pydantic, PyYAML, numpy, anthropic
  (Claude API SDK).
- **Python pipeline (local only):** pandas, GeoPandas, shapely, pyogrio,
  requests, Pillow.
- **Python dev:** pytest, ruff, uvicorn, httpx. Managed with uv.
- **Local document compile:** Laya, PyTorch (CPU).
- **Web:** Vite, React 19, TypeScript (strict), three.js, oxlint; Fredoka and
  Nunito from Google Fonts.
- **APIs and services:** Anthropic Claude API, WPRDC CKAN API, Allegheny County
  ArcGIS REST, AWS Terrain Tiles, Vercel hosting.

All Pittsburgh-specific facts live in `data/config/`. The code iterates over
whatever that folder declares, so extending to another municipality is a data
job, not a rewrite.

## Run it

Requirements: [uv](https://docs.astral.sh/uv/) and Node 20+.

```bash
uv sync                                   # Python 3.14 + runtime/dev deps
cp .env.example .env                      # optional: add ANTHROPIC_API_KEY, set LLM_PROVIDER=anthropic
uv run uvicorn server.app:app --port 8000 --reload
cd web && npm install && npm run dev      # http://localhost:5173 (proxies /api to :8000)
```

Tests and lint:

```bash
uv run pytest && uv run ruff check .
cd web && npx tsc -b && npm run lint
```

**Deploy (Vercel).** Import the repo in Vercel. `vercel.json` builds `web/` as
static files and serves `api/index.py` (FastAPI) as a Python function. Add
`LLM_PROVIDER` and `ANTHROPIC_API_KEY` as environment variables.

### Rebuild the data

To rebuild the parcel index from WPRDC:

```bash
uv sync --group pipeline
uv run python -m pipeline.build_parcels   # ~2 min first run; caches in data/raw/
uv run python -m pipeline.build_terrain   # 3D city heightmap -> web/public/data/terrain.*
uv run python -m pipeline.build_basemap   # streets, neighborhood names, lot outlines -> web/public/data/basemap/
uv run python -m pipeline.docs            # regenerate SOURCES.md + LIMITATIONS.md counts
```

To re-run official ACS tract estimates and parcel-point FEMA/PWSA site context
without rebuilding assessments:

```bash
uv sync --group pipeline
uv run python -m pipeline.enrich_context
uv run python -m pipeline.docs
```

The 2024 ACS table-based summary files need no API key. Raw GIS downloads are
cached in `data/raw/`; remove a source's cached file to fetch its latest version.
Derived facts and coverage counts are checked in. The flood and sewer screens
test a point inside the parcel where a boundary is available, so they can miss
hazards covering only another part of a lot.

### Extract zoning rules

Save the Title Nine sections as text in `data/raw/zoning/` (eCode360 blocks
scripts), set `ANTHROPIC_API_KEY`, then run:

```bash
uv run python -m pipeline.zoning.extract --districts R1D-H RM-M R2-L
```

Rules are in force once their quotes verify. To have a person confirm them,
tick facts in `pipeline/zoning/REVIEW.md` and run
`uv run python -m pipeline.zoning.build_rules --apply`.

### Local Laya and LLM pipeline

All Laya tooling, requirements, curated Laya documents, optional local inputs,
and compiled artifacts live under `dev/laya/`. The app reads the checked-in
`dev/laya/compiled/laya_evidence.json` index but never installs or invokes Laya.
See [dev/laya/README.md](dev/laya/README.md) for passage classification and
structured candidate extraction. Numeric candidates are source-linked and
unapplied; structured sources such as ACS, parcel geometry, and EPA SLD are
integrated through deterministic adapters. Laya classification does not create
or apply zoning rules.

Quote-verified AI-extracted zoning rules are currently in force while labeled
as not checked by a planner. Use the dedicated Title Nine pipeline and
`require_human_review` setting to control that behavior.

## Docs

- [Methods](docs/METHODS.md): each computation in plain language, with formulas
- [Limitations](docs/LIMITATIONS.md): what it gets wrong and who could be harmed
- [Sources](docs/SOURCES.md): dataset registry, generated from config
- [AI disclosure](docs/AI_DISCLOSURE.md): AI used to build it and inside it
- [Backend](docs/BACKEND.md): API principles and security posture

## Next steps and continuation

1. Have a planner check the AI-extracted zoning rules, starting with the
   districts with the most vacant lots: R1D, R2, H, R1A, RM. Then turn on
   `require_human_review`. Extend rules to overlays and the remaining districts
   (LNC, UI, NDI and the Riverfront districts first).
2. Replace the remaining cost and carbon placeholders with verified local
   evidence; evaluate CHAS for income-tier detail.
3. EPA Smart Location Database transit access is joined at block-group level
   (2021 vintage); refresh it with a newer PRT travel-time matrix if current
   route-level access is needed. Combined-sewershed boundaries are loaded, but
   sewer stress still needs capacity or overflow observations.
4. Make scenarios editable (tenure, affordability mix, parking) and add the
   advocates + referee explanation mode.

**Pilot partners we'd approach:** a Pittsburgh CDC (to test the lot-to-memo
workflow on a real parcel), the Department of City Planning (to review the
zoning rules and own the human-review step), the URA and the Pittsburgh Land
Bank (for publicly held lots), Allegheny County (to extend to other
municipalities' codes), and PHFA (for affordability and financing
assumptions). Because every Pittsburgh fact lives in reviewable YAML, a partner
can maintain the data without touching code.

## Team

Three people built Lotline during the build window. Who did what below is read
from the commit history (`git log --no-merges`); everyone also reviewed and
merged each other's work.

_TODO: team name, affiliations, and Devin's full name._

**Leona Chen** ([@leonac24](https://github.com/leonac24)): project lead,
frontend and 3D city

- Wrote the first working code: config system, citywide vacant-parcel pipeline,
  evidence engine and API, then the first web app (map picker, compare view, weights and
  SMAA, work backwards) and the Vercel deploy.
- Built the 3D simulator: the city on real terrain with rivers, bridges,
  streets and neighborhood names; the drag-and-drop lot sandbox with live plan
  analysis and reviewed setbacks drawn as the buildable area; the intro screen;
  tuck-away panels, a phone layout and touch controls.
- Zoning and costs: captured Title Nine text, extracted rules for the R-family,
  H and P districts, and sourced the construction cost, soft cost and grid
  emissions assumptions.
- Merged the Claude Code work (see [AI tool disclosure](#ai-tool-disclosure))
  that added AI lot search, "Ask about this lot", grounded tradeoff
  explanations, the Next steps tab with AI-drafted outreach, share links and the
  first-run tour, and moved the LLM provider from Gemini to the Anthropic API.

**Pranav Singhal** ([@s9kt](https://github.com/s9kt)): product direction,
evidence and data pipeline

- Set the product direction in the first commit: the product-decision record
  ([.grill/cdc-housing-scenario-comparison.md](.grill/cdc-housing-scenario-comparison.md))
  that fixed the CDC as the primary user, and the original project brief
  (`CLAUDE.md`).
- Built the Laya evidence pipeline (`dev/laya/`, `pipeline/laya_compile.py`):
  it compiles versioned Pittsburgh zoning sources into a checked-in evidence
  index with a freshness check and tests. A second stage asks the model for
  numeric candidates that must quote their source and are never applied
  automatically.
- Added `pipeline/enrich_context.py`, which joins 2024 ACS tract income and
  renter burden, frontage and depth estimated from parcel polygons, and EPA
  Smart Location Database transit access to every vacant lot, replacing
  placeholders with sourced values
  ([docs/PLACEHOLDER_PIPELINE.md](docs/PLACEHOLDER_PIPELINE.md)).

**Devin** (commits as `Devin-M5706`): backend and zoning engine

- Hardened the API: hard requirements before weights, every input limit and
  route bound taken from config with tests that keep it that way, the parcel-id
  format in `city.yaml`, and the auditable contract in
  [docs/BACKEND.md](docs/BACKEND.md).
- Zoning engine: separate use and dimensional rules, a citywide ADU rule, the
  height rule, and lot fit from building footprints.
- The "what to find out" work plan: `core/inquiries.py` turns each parcel's
  unknowns into questions, who can answer them and what to ask for, and
  `web/src/lib/leverage.ts` orders them by how much each answer could move the
  ranking.
- Wrote the design for adding tax to the evidence layer.

## Originality

Built from scratch during the hackathon build window, which opened Saturday,
September 26, 2026 at 9:00 a.m. ET. No code predates kickoff, and the commit
history is intact. Libraries, datasets and APIs are listed above. The repository
stays public after the event.
