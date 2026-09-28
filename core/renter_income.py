"""Estimate the renter-household share below a proposed income requirement.

ACS B25118 reports income *bins*, not an exact income distribution. A straight
line within a finite bin supplies a point estimate; the interval allows every
household in a crossed bin to fall on either side and expands counts by their
published 90% margins of error. This is tract context, not a parcel measurement.
"""

from __future__ import annotations

from math import isfinite
from typing import Any


def _number(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if isfinite(result) else None


def renter_share_below_income(
    distribution: dict[str, Any] | None,
    income_required: float,
    income_low: float | None = None,
    income_high: float | None = None,
) -> dict[str, float | str] | None:
    """Return percent of renter households below a required annual income."""
    if not isinstance(distribution, dict) or not isinstance(distribution.get("bins"), list):
        return None
    total = _number(distribution.get("total_renter_households"))
    total_moe = _number(distribution.get("total_moe_90")) or 0.0
    if total is None or total <= 0:
        return None
    bins = []
    for row in distribution["bins"]:
        if not isinstance(row, dict):
            return None
        start = _number(row.get("lower_usd"))
        end = _number(row.get("upper_usd"))
        count = _number(row.get("households"))
        moe = _number(row.get("moe_90")) or 0.0
        if start is None or count is None or count < 0 or (end is not None and end <= start):
            return None
        bins.append((start, end, count, max(0.0, moe)))
    if not bins:
        return None
    bins.sort(key=lambda row: row[0])

    def central(threshold: float) -> float:
        result = 0.0
        for start, end, count, _ in bins:
            if threshold <= start:
                continue
            if end is not None and threshold >= end:
                result += count
            elif end is None:
                # Open top bin has no supported within-bin shape. Its midpoint
                # is an explicit point scenario; the interval below spans it.
                result += 0.5 * count
            else:
                result += count * min(1.0, (threshold - start) / (end - start))
        return min(100.0, max(0.0, 100.0 * result / total))

    threshold_low = max(0.0, income_low if income_low is not None else income_required)
    threshold_high = max(threshold_low, income_high if income_high is not None else income_required)
    fully_below = sum(max(0.0, count - moe) for start, end, count, moe in bins
                      if end is not None and end <= threshold_low)
    possibly_below = sum(count + moe for start, _, count, moe in bins if start < threshold_high)
    low = 100.0 * fully_below / (total + total_moe)
    high = 100.0 * possibly_below / max(1.0, total - total_moe)
    value = central(income_required)
    return {
        "value": round(value, 2),
        "low": round(max(0.0, min(low, value)), 2),
        "high": round(min(100.0, max(high, value)), 2),
        "unit": "% renter households",
        "interval_type": "ACS 90% MOE plus income-bin and cost scenario bounds",
    }
