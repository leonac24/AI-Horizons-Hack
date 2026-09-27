"""Estimate unmatched context from distinct local source geographies.

These are disclosed geographic/model fallbacks, not measurements of an
unmatched parcel or tract. Quantile bands describe donor variation.
"""

from __future__ import annotations

import hashlib
import json
from statistics import median, quantiles

from core.artifact_files import replace_text
from core.config import ROOT


def donor_band(values: list[float]) -> dict:
    if not values:
        raise ValueError("No usable local donor values")
    deciles = quantiles(values, n=10, method="inclusive") if len(values) > 1 else values * 9
    return {"value": median(values), "low": deciles[0], "high": deciles[-1], "sample_size": len(values)}


def estimate_context_fallbacks(parcels: list[dict]) -> dict:
    tracts = {}
    burden_tracts = {}
    blocks = {}
    ratios = []
    for parcel in parcels:
        if parcel.get("tract") and parcel.get("tract_median_household_income") is not None:
            tracts[parcel["tract"]] = parcel
        if parcel.get("tract") and parcel.get("tract_renter_cost_burden_share") is not None:
            burden_tracts[parcel["tract"]] = parcel
        if parcel.get("block_group") and parcel.get("transit_access_index") is not None:
            block_id = f"{parcel.get('tract', '')}:{parcel['block_group']}"
            blocks[block_id] = parcel["transit_access_index"]
        frontage, depth = parcel.get("frontage_ft"), parcel.get("depth_ft")
        if frontage and depth and frontage > 0 and depth > 0:
            ratios.append(depth / frontage)
    burden_rows = list(burden_tracts.values())
    return {
        "tract_median_household_income": {
            **donor_band([r["tract_median_household_income"] for r in tracts.values()]),
            "unit": "USD/yr", "source_ids": ["acs_5yr"],
            "limitations": "Median of distinct matched Pittsburgh tract medians; donor 10th–90th percentiles are a geographic scenario range, not a citywide household median or confidence interval.",
        },
        "tract_renter_cost_burden_share": {
            **donor_band([r["tract_renter_cost_burden_share"] for r in burden_rows]),
            "unit": "share of renter households", "source_ids": ["acs_5yr"],
            "limitations": "Median of distinct matched Pittsburgh tract renter-burden shares; donor 10th–90th percentiles describe spatial variability, not the unmatched tract's confidence interval.",
        },
        "jobs_access_index": {
            **donor_band(list(blocks.values())), "unit": "index (regional max = 1)",
            "source_ids": ["epa_smart_location"],
            "limitations": "Median of distinct matched local block-group EPA SLD D5DRI scores; donor range is a geographic proxy for unmatched parcels, not current route-level access.",
        },
        "lot_depth_to_frontage_ratio": {
            **donor_band(ratios), "unit": "depth / frontage", "source_ids": ["wprdc_assessments"],
            "limitations": "Median depth/frontage ratio among matched legal-description dimensions in the vacant-parcel cohort; donor variation is a drawing and form-fit scenario, not legal frontage.",
        },
    }


def build() -> dict:
    path = ROOT / "data" / "processed" / "parcels.json"
    parcels = json.loads(path.read_text(encoding="utf-8"))["parcels"]
    context_path = ROOT / "data" / "processed" / "parcel_context.jsonl"
    for line in context_path.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        parcels[row["id"]].update(row)
    result = {
        "model_id": "lotline:local-donor-fallbacks:v1", "as_of": "2026-09-27",
        "estimation_source_id": "lotline_context_estimates",
        "source_sha256": {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in (path, context_path)},
        "assumptions": estimate_context_fallbacks(list(parcels.values())),
    }
    output = ROOT / "data" / "models" / "context_fallbacks.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    replace_text(output, json.dumps(result, indent=2) + "\n")
    return result


if __name__ == "__main__":
    print(json.dumps(build()["assumptions"], indent=2))
