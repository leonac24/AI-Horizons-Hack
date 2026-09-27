# Local Laya and LLM pipeline

This directory contains all Laya-specific tooling, curated Laya source snapshots,
local-only inputs, dependencies, and compiled artifacts. The API reads only the
small checked-in `compiled/laya_evidence.json` index; it does not install or run
Laya. Local source documents and model weights are not committed.

## Passage classification

From the repository root, create a local environment and install CPU PyTorch and
the isolated Laya requirements:

```bash
python3 -m venv dev/laya/.venv
dev/laya/.venv/bin/python -m pip install 'torch==2.14.0+cpu' --index-url https://download.pytorch.org/whl/cpu
dev/laya/.venv/bin/python -m pip install -r dev/laya/requirements.txt
HF_HOME=dev/laya/cache dev/laya/.venv/bin/python -m dev.laya.compile
HF_HOME=dev/laya/cache dev/laya/.venv/bin/python -m dev.laya.compile --check
```

Text/PDF inputs with a registered source id go under
`dev/laya/raw/<source_id>/`. Curated Laya documents live under
`dev/laya/sources/<source_id>/`. Zoning snapshots under `data/sources/zoning/`
and Title Nine text under `data/raw/zoning/` are also classified as evidence
leads. Keep public documents only. The classifier labels passages; it does not
extract or apply numerical values.

## Candidate extraction

The second stage routes passages with Laya and asks the configured Anthropic
model for structured numeric claims. It checks that the target is an eligible
placeholder, the unit matches, and the short quote appears in the supplied
passage. It stores source id, document and passage hashes, geography, period,
and table/section in `compiled/metric_candidates.json`.

```bash
export ANTHROPIC_API_KEY=...
HF_HOME=dev/laya/cache dev/laya/.venv/bin/python -m dev.laya.extract_candidates
```

Set `ZONING_EXTRACT_MODEL` to select the Anthropic model; otherwise the local
candidate step uses the same default as the existing zoning extractor.

The output is a candidate ledger and is never read by the application or copied
to `data/config/assumptions.yaml` automatically. Candidate extraction cannot
turn a national statistic into a Pittsburgh value, treat an unknown as zero, or
claim spare sewer capacity. Context-specific observations must be integrated
through a parcel/tract/source adapter with matching geography. For zoning, use
`pipeline.zoning.extract` and `pipeline.zoning.build_rules`: the current policy
puts quote-verified AI rules in force while labeling them as not planner-checked.
Laya topic classification alone never writes zoning rules.

## Current source limitations

Laya does not download sources. Use deterministic adapters for structured
datasets: ACS, parcel geometry, FEMA/PWSA overlays, and EPA SLD transit access
are joined by `pipeline.enrich_context`. Save permitted public documents locally
for candidate extraction. Geotechnical cost shares, household VMT, and sewer
capacity remain unknown/placeholders until matching evidence and an integration
exist. A candidate is evidence for adoption, not a replacement for source ETL.
