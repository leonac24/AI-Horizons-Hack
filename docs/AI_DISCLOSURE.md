# AI disclosure

## AI used to build Lotline

- **Claude Code (Anthropic, Claude Opus 5.5)** wrote most of the first-pass code
  and docs, working with the team: the pipeline, engine, API, frontend and
  tests. A person on the team decided each design question. Code was
  checked by the test suite (config validation, scoring math, zoning evaluation,
  a citywide coverage test, a no-hardcoding fixture) and by running the app.
- The 3D simulator was built from a design handoff (an HTML/three.js
  prototype) that the team supplied. Claude Code ported it to the repo's
  React/TypeScript code. It replaced the prototype's placeholder model and
  sample zoning rules with API data, because those were invented and are not
  shipped.
- Claude Code also looked up and checked the dataset endpoints listed in
  `sources.yaml`, calling the WPRDC CKAN API directly.
- Claude Code drafted the property tax structure (`data/config/tax.yaml`), the
  comps pipeline and the stand-in values in `assumptions.yaml`. It did **not**
  write millage rates or abatement terms from memory: every such value is a
  labeled placeholder until a teammate verifies it against the published rate or
  ordinance, the same review rule as zoning.

## AI inside Lotline

| Where | Model | What it may do | How it's checked |
|---|---|---|---|
| Zoning extraction (offline, `pipeline/zoning/extract.py`) | Gemini, `ZONING_EXTRACT_MODEL` (default `gemini-2.5-pro`) | Read Title Nine text and propose per-district rules | Output must validate against a schema. Each rule must quote the source verbatim (< 25 words) or it is dropped. **A teammate reviews every rule and sets `reviewed: true`.** Unreviewed rules never change what the app shows. |
| Tradeoff explanations (runtime, `server/explain.py`) | Gemini, `LLM_MODEL` (default `gemini-3.8-flash`) | Restate computed metrics as plain-language tradeoffs | Every sentence must cite metric IDs from the input and use only numbers from the input. If not, the server discards the output and shows a deterministic template. The UI says which one you're seeing. |

- With `LLM_PROVIDER=none` the app runs with no AI at runtime.
- **Data sent to Gemini:** only public information. That is zoning code text,
  or computed metrics for a public parcel together with the user's current
  slider weights. No personal data. On Gemini's free tier, Google may use
  submitted content to improve its products.
- **What AI never does here:** set a weight, change a metric, rank options,
  or decide a zoning status without human review.
