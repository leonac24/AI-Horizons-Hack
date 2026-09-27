# Lotline

**Pittsburgh Housing Typology, Equity & Climate Matchmaker.** AI Horizons 2026 ·
AI for Housing Hackathon · Challenge 03.

Pick any vacant lot in the City of Pittsburgh (22,183 of them, from county
assessment records) and compare six kinds of housing that could go there:

- who each one houses and what it costs;
- what it emits over 30 years;
- what the Zoning Code allows;
- how the ranking changes depending on whose priorities you use.

> Decision support only — not zoning, legal, or financial advice. Confirm with
> the City of Pittsburgh Department of City Planning.

## Who it's for

- **Community development corporations** choosing what to propose on a lot.
- **City Planning and the URA** weighing options for publicly held land.
- **Residents** who want to see the tradeoffs, and the value judgments, behind a
  proposal.

## What it does

- **Pick a lot.** A stylized 3D model of Pittsburgh on real terrain (rivers,
  bluffs and hollows from public elevation data) with every vacant parcel at
  its real location. Search by address or parcel ID, filter by lot size,
  zoning, public ownership or site hazard, or start from suggested lots spread
  across the city. Click a lot to fly into it.
- **Build on it.** Drag housing types from the palette onto the lot. The pad
  uses the lot's real frontage and depth from the deed legal description (71%
  of vacant parcels; the rest are labeled placeholders). Buildings snap, rotate,
  and turn red if they're off the lot or overlapping. Undo and redo are
  supported, and a Before/After toggle shows the lot as it is today. Every
  change re-evaluates "Your plan" on the server.
- **Compare.** Your plan ranked next to each housing type's own option:
  - zoning status with Title Nine citations; buildings whose use is prohibited
    get a red outline, and the plan is excluded from the ranking;
  - "Could this household afford it?" for illustrative households;
  - carbon over time, with a year slider and crossover years;
  - public revenue to the City, school district and county over the horizon,
    net of any reviewed abatement, with a "high revenue, high exclusion" flag
    when the top-revenue option is also the least affordable.
- **Whose priorities?** Weight sliders and stakeholder presets. SMAA bars show
  how often each option ranks first once weights and uncertainty are sampled.
  A one-line "ranking flip" gives the smallest weight change that swaps the top
  two.
- **Explain.** A grounded plain-language explanation in which every sentence
  cites the metrics it uses.
- **Work backwards.** Pick a housing type, a home count and an income tier. See
  the zoning rules that fail, the subsidy gap per home, and the site flags.
- **What we don't know.** Every placeholder, unconnected source and unreviewed
  zoning district, plus citywide coverage counts for joined data.
- **Memo.** One printable page for a community meeting.

**Core principle: evidence and values are separate.** Metrics carry ranges and
provenance:

- solid = observed
- dashed = modeled
- outlined = assumption
- hatched = placeholder

Weights are shown in their own color and never enter a metric.

**Human in the loop.** Zoning rules are extracted by an LLM, and each must quote
the code verbatim. A teammate then reviews every rule before it can affect the
app (`pipeline/zoning/rules_review.yaml`). Until then, the lot shows
"Needs planner review". Tax law gets the same treatment: millage and abatement
terms are placeholders until a teammate verifies them (`data/config/tax.yaml`,
`assumptions.yaml`).

## Run it

Requirements: [uv](https://docs.astral.sh/uv/) and Node 20+.

```bash
uv sync                                   # Python 3.14 + runtime/dev deps
cp .env.example .env                      # optional: add GEMINI_API_KEY, set LLM_PROVIDER=gemini
uv run uvicorn server.app:app --port 8000 --reload
cd web && npm install && npm run dev      # http://localhost:5173 (proxies /api to :8000)
```

To rebuild the parcel index from WPRDC:

```bash
uv sync --group pipeline
uv run python -m pipeline.build_parcels   # ~2 min first run; caches in data/raw/
uv run python -m pipeline.build_terrain   # 3D city heightmap -> web/public/data/terrain.*
uv run python -m pipeline.build_comps     # assessed-value comps per housing type and neighborhood
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
Derived facts and coverage counts are checked in. The
flood and sewer screens test a point inside the parcel where a boundary is
available, so they can miss hazards covering only another part of a lot.

To extract zoning rules, save the Title Nine sections as text in
`data/raw/zoning/` (eCode360 blocks scripts), set `GEMINI_API_KEY`, then run:

```bash
uv run python -m pipeline.zoning.extract --districts R1D-H RM-M R2-L
```

Afterwards, review `pipeline/zoning/rules_review.yaml` by hand.

Tests and lint:

```bash
uv run pytest && uv run ruff check .
cd web && npx tsc -b && npm run lint
```

**Deploy (Vercel).** Import the repo in Vercel. `vercel.json` builds `web/` as
static files and serves `api/index.py` (FastAPI) as a Python function. Add
`LLM_PROVIDER` and `GEMINI_API_KEY` as environment variables.

## Stack

- **Pipeline:** Python 3.14 (uv), pandas, GeoPandas, shapely, pyogrio, requests.
- **Engine and API:** numpy, pydantic, PyYAML, FastAPI, google-genai.
- **Web:** Vite, React 19, TypeScript (strict), three.js for the 3D city and
  lot views, with Fredoka and Nunito fonts from Google Fonts. Pipeline adds
  Pillow to decode elevation tiles for the terrain bake.

All Pittsburgh-specific facts live in `data/config/`. The code iterates over
whatever that folder declares.

## Docs

- [Methods](docs/METHODS.md)
- [Limitations](docs/LIMITATIONS.md)
- [Sources](docs/SOURCES.md)
- [AI disclosure](docs/AI_DISCLOSURE.md)

## Next steps

1. Review zoning rules for the districts with the most vacant lots: H, R1D-H,
   RM-M, R1D-L, R2-L.
2. Replace remaining cost and carbon placeholders with verified local evidence;
   evaluate CHAS for income-tier detail.
3. Build a measured PRT travel-time matrix with a walking network and job
   destinations, or obtain the University of Minnesota's block-level 2024
   transit-access data (the linked repository rejected access during this
   build). Combined-sewershed boundaries are loaded, but sewer stress still
   needs capacity or overflow observations.
4. Add the advocates + referee explanation mode.
5. Verify City, School District and County millage, homestead exclusions and the
   residential abatement terms; then model LIHTC in Work backwards.

**Pilot partners we'd approach:** a Pittsburgh CDC, the Department of City
Planning, the URA, and the Pittsburgh Land Bank.

## Team

_TBD._
