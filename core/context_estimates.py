"""Disclosed local donor estimates for unmatched parcel context."""

from __future__ import annotations

import json
from functools import lru_cache

from core.config import ROOT


@lru_cache(maxsize=2)
def _model(version: tuple[int, int]) -> dict:
    return json.loads((ROOT / "data" / "models" / "context_fallbacks.json").read_text(encoding="utf-8"))


def context_fallback(key: str) -> dict:
    path = ROOT / "data" / "models" / "context_fallbacks.json"
    stat = path.stat()
    model = _model((stat.st_mtime_ns, stat.st_size))
    value = dict(model["assumptions"][key])
    return {
        **value, "provenance": "modeled", "evidence_tier": "local_donor_geographic_fallback",
        "interval_type": "donor 10th–90th percentile scenario range",
        "geography": "pooled matched Pittsburgh geographies; target geography unmatched",
        "source_ids": [*value["source_ids"], model["estimation_source_id"]],
        "model_id": model["model_id"], "as_of": model["as_of"],
        "confirmation_needed": "Replace with a valid target-geography source match when available.",
    }
