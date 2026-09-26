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

- **Pick a lot.** A citywide map of vacant parcels. Search by address or parcel
  ID, jump to a neighborhood, filter by lot size, zoning, public ownership or
  site hazard, or start from suggested lots spread across the city.
- **Compare.** Scenario cards with a "tradeoff receipt" for each option:
  - zoning status with Title Nine citations;
  - "Could this household afford it?" for illustrative households;
  - carbon over time, with crossover years.
- **Whose priorities?** Weight sliders and stakeholder presets. SMAA bars show
  how often each option ranks first once weights and uncertainty are sampled.
  A one-line "ranking flip" gives the smallest weight change that swaps the top
  two.
- **Explain.** A grounded plain-language explanation in which every sentence
  cites the metrics it uses.
- **Work backwards.** Pick a housing type, a home count and an income tier. See
  the zoning rules that fail, the subsidy gap per home, and the site flags.
- **What we don't know.** Every placeholder, unconnected source and unreviewed
  zoning district.
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
"Needs planner review".

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
uv run python -m pipeline.docs            # regenerate SOURCES.md + LIMITATIONS.md counts
```

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
- **Web:** Vite, React 19, TypeScript (strict), MapLibre GL JS with the
  OpenFreeMap basemap, Recharts.

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
2. Replace the placeholders. HUD income limits, ACS and CHAS by tract (needs a
   Census API key), and a sourced set of Pittsburgh construction costs.
3. Connect FEMA flood, the ALCOSAN/PWSA sewersheds, and a PRT GTFS travel-time
   matrix with a slope-aware walk leg.
4. Add the advocates + referee explanation mode.

**Pilot partners we'd approach:** a Pittsburgh CDC, the Department of City
Planning, the URA, and the Pittsburgh Land Bank.

## Team

_TBD._
