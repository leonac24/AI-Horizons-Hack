from pipeline.context_fallbacks import estimate_context_fallbacks
from pipeline.planning_estimates import annual_payment_rate


def test_donor_fallback_does_not_weight_tracts_by_vacant_parcel_count():
    low = {"tract": "one", "block_group": 1, "tract_median_household_income": 20000,
           "tract_renter_cost_burden_share": .6, "transit_access_index": .2,
           "frontage_ft": 20, "depth_ft": 80}
    high = {**low, "tract": "two", "tract_median_household_income": 80000,
            "transit_access_index": .8}
    result = estimate_context_fallbacks([low] * 100 + [high])
    assert result["tract_median_household_income"]["value"] == 50000
    assert result["tract_median_household_income"]["sample_size"] == 2
    assert result["jobs_access_index"]["sample_size"] == 2
    assert result["jobs_access_index"]["value"] == .5


def test_zero_interest_capital_recovery_remains_finite():
    assert annual_payment_rate(0, 30) == 1 / 30
