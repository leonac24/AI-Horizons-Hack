# Parcel evidence pipeline

Lotline keeps one row per Pittsburgh vacant-parcel PIN in `data/processed/parcels.json`
and `data/processed/parcel_evidence.jsonl`. The JSONL artifact has the contract
`{id, parcel, evidence}`. `parcel` is an empty object when the base index already
contains all direct parcel fields. Each evidence field records its value,
geography, date, source and snapshot IDs, provenance, interval meaning,
limitations, and what must be confirmed. The companion
`parcel_evidence_manifest.json` records source status and hashes; the API hashes
the served evidence and sales files into its analysis cache key.

## Rebuild

From the repository root:

```bash
uv sync --group pipeline
uv run --group pipeline python -m pipeline.build_parcels
uv run --group pipeline python -m pipeline.docs
```

The build downloads public sources into ignored `data/raw/` cache files, keeps
the entire source vacant cohort, and writes the index, context, evidence, sales,
GeoJSON, manifest, and pipeline report. A parcel without reliable coordinates
remains in the API and search; it has no map point, and location-dependent
zoning and hazard claims stay unknown. Zero area or land assessment values from
the source are retained in an explicit raw-value evidence record, while usable
area or acquisition inputs stay null until confirmed.

The sales index accepts only positive-price, valid-code, single-parcel
transactions with a parseable date and a matched vacant PIN. It does not turn
government transfers, multi-parcel deeds, or assessed value into arm's-length
market observations. Comparable land values are models using recent qualified
sales, with local and size matching disclosed. Assessed land value can only be
used as a separately labeled acquisition scenario when sales are insufficient.

ACS B25118 renter-income bins are joined at the parcel's tract when possible.
For missing tract links, the source county row is a labeled geographic fallback.
Bin estimates and 90% margins of error remain tract or county context, not a
measured characteristic of a parcel or its residents. The share below a
scenario's required income is interpolated within finite bins and bounded by
the published margins and cost range.

## Models and unresolved inputs

`core/finance_model.py` builds a separate scenario for rental and ownership:
line-item uses, financing, operating costs, taxes, and required payment or rent.
Its public HUD/PHFA/PWSA/Freddie Mac references and declared assumptions are
returned with each envelope. A target ownership sale price is a cost-plus-margin
scenario; actual new-home market value requires validated sale or appraisal data.

`core/environment_model.py` accepts quantity, energy, travel and annual grid
series envelopes. It returns a partial carbon series only when the required
inputs exist, and explicitly lists omitted fuel and fleet effects. Its added
wastewater figure is a design-flow scenario, never a capacity determination.
The public BTS LATCH importer lives in `pipeline/environment_inputs.py`:

```bash
uv run --group pipeline python -m pipeline.environment_inputs download-latch \
  --out data/raw/bts_latch/2017/latch.csv
uv run --group pipeline python -m pipeline.environment_inputs latch-index --help
uv run --group pipeline python -m pipeline.environment_inputs join-latch --help
```

LATCH is a 2017 weekday household travel context at 2010 tract geography. Its
actual column names and profile must be selected from the downloaded snapshot;
annualization needs a stated weekday/weekend conversion and a 2010-to-2020
tract relationship. A weekday value is never silently converted into annual
vehicle miles. `data/config/environment_sources.yaml` tracks the remaining
material, energy, grid and sewer source connections. Written utility capacity,
project bids, lender terms and insurance quotes remain parcel-specific checks.

## Application check

Run the API and UI locally, then open a real PIN in the browser:

```bash
uv run uvicorn server.app:app --port 8000
cd web && npm run dev
```

`GET /api/health` reports the number of indexed PINs and evidence hash;
`GET /api/analysis/{PIN}` returns the cards, source envelopes, and hash;
`GET /api/unknowns` reports field coverage. The browser shows a provenance tag,
range and source details for each card. Search also finds PINs absent from the
map because their coordinates are unconfirmed.
