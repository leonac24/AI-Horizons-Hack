# TODO

## Blocked by Gemini free-tier quota (2026-09-26)

- [ ] **Extract zoning rules for R1D-M, R2-H, R1A-H.** These are 3 of the 10
      districts with the most vacant parcels (1,183 / 1,166 / 963 lots). The
      extraction run hit `503 UNAVAILABLE` (model overloaded) and then
      `429 RESOURCE_EXHAUSTED` on `gemini-3.8-flash`. A retry on
      `gemini-3.5-flash` hung and was stopped. The code text they need is
      already in `data/raw/zoning/`. Once the quota resets, run:

      ```bash
      uv run --env-file .env python -m pipeline.zoning.extract --districts R1D-M R2-H R1A-H
      ```

      Then check that all three appear in `pipeline/zoning/rules_review.yaml`
      with `reviewed: false`, and hand them to the rule reviewer.

      Tips: set `ZONING_EXTRACT_MODEL=gemini-3.8-flash` in `.env`
      (`gemini-2.5-pro` is retired for new keys, and Pro models have no
      free-tier quota). If a run sits for minutes with no new district in the
      rules file, stop it and try again later. The Gemini client has no
      request timeout.
