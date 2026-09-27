from core.renter_income import renter_share_below_income


def test_renter_share_uses_bins_and_keeps_crossed_bin_uncertain():
    counts = {
        "total_renter_households": 100,
        "total_moe_90": 5,
        "bins": [
            {"lower_usd": 0, "upper_usd": 20000, "households": 40, "moe_90": 4},
            {"lower_usd": 20000, "upper_usd": 40000, "households": 30, "moe_90": 3},
            {"lower_usd": 40000, "upper_usd": None, "households": 30, "moe_90": 3},
        ],
    }
    lower = renter_share_below_income(counts, 25000)
    higher = renter_share_below_income(counts, 35000)
    assert lower is not None and higher is not None
    assert lower["value"] == 47.5
    assert higher["value"] == 62.5
    assert lower["low"] <= lower["value"] <= lower["high"]
    assert higher["low"] <= higher["value"] <= higher["high"]
    assert higher["value"] > lower["value"]
