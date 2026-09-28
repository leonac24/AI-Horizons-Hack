from core.finance_model import EVIDENCE_FIELDS, build_finance_defaults, estimate_finance


def env(value, low=None, high=None, unit="USD", source="fixture", vintage="2026-01"):
    return {
        "value": value, "low": value if low is None else low,
        "high": value if high is None else high, "unit": unit,
        "provenance": "assumption", "evidence_tier": "declared_scenario",
        "interval_type": "scenario_range", "geography": "Pittsburgh",
        "source_ids": [source], "source_snapshot_ids": [vintage],
        "as_of": "2026-01-01", "limitations": [], "confirmation_needed": "Confirm input.",
    }


def base_defaults():
    return {
        "analysis_date": "2026-09-27",
        "hard_cost_psf": env(200, 180, 220, "USD/sf", "hud_hcc", "2024"),
        "site_cost_usd": env(10000, 5000, 20000),
        "soft_cost_share": env(0.3, 0.2, 0.4, "share", "project_budget_template"),
        "contingency_share": env(0.1, 0.05, 0.15, "share", "project_budget_template"),
        "hud_tdc_benchmark_per_unit": env(300000, 280000, 320000, "USD/unit", "hud_tdc", "2024"),
        "rental_debt_share": env(0.70, 0.65, 0.75, "share of uses", "rental_sources_uses"),
        "rental_equity_share": env(0.30, 0.25, 0.35, "share of uses", "rental_sources_uses"),
        "rental_subsidy_share": env(0.0, 0.0, 0.0, "share of uses", "rental_sources_uses"),
        "rental_debt_rate": env(0.065, 0.06, 0.07, "annual rate", "rental_loan"),
        "rental_debt_term_years": env(30, 30, 30, "years", "rental_loan"),
        "rental_equity_return_rate": env(0.05, 0.04, 0.06, "annual rate", "rental_sources_uses"),
        "vacancy_rate": env(0.05, 0.03, 0.08, "share", "phfa_guidance", "2025-2026"),
        "rental_dscr": env(1.15, 1.1, 1.2, "ratio", "lender_scenario"),
        "taxes_per_unit_month": env(100, 80, 120, "USD/unit/month", "tax_model"),
        "insurance_per_unit_month": env(80, 60, 100, "USD/unit/month", "insurance_quote"),
        "utilities_per_unit_month": env(90, 70, 110, "USD/unit/month", "operator_budget"),
        "maintenance_per_unit_month": env(100, 80, 130, "USD/unit/month", "operator_budget"),
        "management_per_unit_month": env(90, 70, 110, "USD/unit/month", "operator_budget"),
        "reserves_per_unit_month": env(100, 80, 130, "USD/unit/month", "operator_budget"),
        "for_sale_purchase_price": env(250000, 220000, 280000, "USD/unit", "declared_home_price", "2026-01"),
        "buyer_down_payment_share": env(0.2, 0.1, 0.25, "share", "buyer_scenario"),
        "buyer_mortgage_rate": env(0.065, 0.06, 0.07, "annual rate", "freddie_pmms", "2026-09-24"),
        "buyer_mortgage_term_years": env(30, 30, 30, "years", "buyer_scenario"),
        "property_tax_mills": env(26.557, 25, 28, "mills", "pittsburgh_tax_rates", "2026"),
        "buyer_insurance_per_unit_month": env(120, 100, 140, "USD/unit/month", "insurance_quote"),
        "transfer_tax_rates": [
            env(0.04, 0.04, 0.04, "share", "city_transfer_tax", "2026-09"),
            env(0.05, 0.05, 0.05, "share", "county_transfer_tax", "2026-09"),
        ],
    }


def sales():
    rows = []
    for i, price in enumerate((40000, 50000, 60000, 70000)):
        rows.append({"sale_price": price, "sale_date": f"2025-0{i+1}-15",
                     "parcel_area_sqft": 5000, "arm_length": True, "vacant": True,
                     "source_id": f"sale-{i}", "snapshot_id": "assessment-2026",
                     "geography": "Allegheny County"})
    rows += [
        {"sale_price": 50000, "sale_date": "2025-01-01", "parcel_area_sqft": 5000,
         "arm_length": False, "vacant": True, "source_id": "non-arm"},
        {"sale_price": 90000, "sale_date": "2025-01-01", "parcel_area_sqft": 5000,
         "arm_length": True, "vacant": False, "source_id": "not-vacant"},
        {"sale_price": 90000, "sale_date": "2010-01-01", "parcel_area_sqft": 5000,
         "arm_length": True, "vacant": True, "source_id": "stale"},
    ]
    return rows


def test_sales_comps_make_labeled_range_and_count_without_assessment_value():
    result = estimate_finance({"pin": "x", "lot_area_sf": 5000, "assessed_value": 1},
        "rowhouse", 4, 900, {"county_sales": {"value": sales()}}, base_defaults())
    value = result["land_value"]["value"]
    assert value["value"] == 55000
    assert value["low"] <= value["value"] <= value["high"]
    assert value["evidence_tier"] == "county_size_matched_sales_estimate"
    assert value["provenance"] == "modeled"
    assert any("Lot-size matching alone" in x for x in value["limitations"])
    assert value["sample_size"] == 4
    assert result["land_value"]["comparable_count"]["value"] == 4
    assert "assessed_value" not in value["source_ids"]
    assert set(EVIDENCE_FIELDS) <= value.keys()


def test_broad_sales_fallback_and_declared_fallback_are_distinct():
    rows = sales()[:2]
    result = estimate_finance({"lot_area_sqft": 5000}, "detached", 1, 1000,
        {"county_sales": rows}, {**base_defaults(), "land_value": env(45000, 30000, 60000, source="agency-scenario")})
    assert result["land_value"]["value"]["evidence_tier"] == "countywide_sales_estimate"
    assert result["land_value"]["comparable_count"]["value"] == 2

    none = estimate_finance({"lot_area_sqft": 5000}, "detached", 1, 1000,
        {"county_sales": []}, {**base_defaults(), "land_value": env(45000, 30000, 60000, source="agency-scenario")})
    assert none["land_value"]["value"]["evidence_tier"] == "declared_scenario"
    assert none["land_value"]["value"]["sample_size"] is None


def test_line_item_budget_keeps_hud_tdc_as_non_additive_benchmark():
    result = estimate_finance({"lot_area_sqft": 5000}, "rowhouse", 2, 1000,
        {"county_sales": sales()}, base_defaults())
    budget = result["development_cost"]
    hard = budget["line_items"]["hard_construction"]["value"]
    site = budget["line_items"]["site_work"]["value"]
    soft = budget["line_items"]["soft_costs"]["value"]
    contingency = budget["line_items"]["contingency"]["value"]
    land = budget["line_items"]["land"]["value"]
    assert budget["total_uses"]["value"] == hard + site + soft + contingency + land
    assert budget["hud_tdc_benchmark_per_unit"]["value"] == 300000
    assert budget["total_uses"]["value"] != hard + site + soft + contingency + land + 300000
    assert any("TDC is not added" in item for item in budget["total_uses"]["limitations"])
    assert budget["total_uses"]["provenance"] == "assumption"
    assert {"hud_hcc", "project_budget_template", "sale-0"} <= set(budget["total_uses"]["source_ids"])
    assert "assessment-2026" in budget["total_uses"]["source_snapshot_ids"]


def test_rental_and_for_sale_are_separate_and_transfer_conflict_stays_a_range():
    result = estimate_finance({"lot_area_sqft": 5000}, "small_multi", 4, 700,
        {"county_sales": sales()}, base_defaults())
    assert result["rental"]["monthly_rent_required"]["value"] > 0
    assert result["for_sale"]["buyer_monthly_cost"]["value"] > 0
    assert result["rental"]["monthly_rent_required"]["provenance"] == "assumption"
    assert result["for_sale"]["buyer_monthly_cost"]["provenance"] == "assumption"
    assert "freddie_pmms" in result["for_sale"]["buyer_monthly_cost"]["source_ids"]
    assert "pittsburgh_tax_rates" in result["for_sale"]["buyer_monthly_cost"]["source_ids"]
    tax = result["for_sale"]["transfer_tax_rate_conflict"]
    assert (tax["low"], tax["high"]) == (0.04, 0.05)
    assert tax["evidence_tier"] == "conflicting_sources"
    assert set(tax["source_ids"]) == {"city_transfer_tax", "county_transfer_tax"}
    gross_tax = result["for_sale"]["transfer_tax_gross"]
    assert gross_tax["low"] == 220000 * 0.04
    assert gross_tax["high"] == 280000 * 0.05


def test_absent_market_price_and_missing_rental_inputs_remain_unresolved():
    defaults = base_defaults()
    defaults.pop("for_sale_purchase_price")
    defaults.pop("management_per_unit_month")
    result = estimate_finance({"lot_area_sqft": 5000}, "rowhouse", 2, 900,
        {"county_sales": sales()}, defaults)
    assert result["for_sale"]["purchase_price"]["value"] is None
    assert result["rental"]["monthly_rent_required"]["value"] is None


def test_no_comps_without_declared_fallback_does_not_create_a_zero_land_price():
    defaults = base_defaults()
    result = estimate_finance({"lot_area_sqft": 5000}, "rowhouse", 2, 900,
        {"county_sales": []}, defaults)
    assert result["land_value"]["value"]["value"] is None
    assert result["development_cost"]["total_uses"]["value"] is None


def test_neighborhood_comps_take_precedence_over_countywide_comps():
    rows = []
    for i, price in enumerate((40000, 50000, 60000, 90000, 100000, 110000)):
        row = sales()[i % 4].copy()
        row["sale_price"] = price
        row["parcel_area_sqft"] = 5000
        row["source_id"] = f"geo-{i}"
        row["neighborhood"] = "target hood" if i < 3 else "other hood"
        rows.append(row)
    result = estimate_finance({"lot_area_sf": 5000, "neighborhood": "Target Hood"}, "rowhouse", 1, 900,
        {"county_sales": rows}, base_defaults())
    estimate = result["land_value"]["value"]
    assert estimate["evidence_tier"] == "neighborhood_sales_estimate"
    assert estimate["sample_size"] == 3
    assert estimate["geography"] == "parcel neighborhood matches"


def test_assessed_value_is_only_a_labeled_acquisition_scenario():
    result = estimate_finance({"lot_area_sf": 5000, "land_value_usd": 12000}, "rowhouse", 1, 900,
        {"county_sales": []}, base_defaults())
    land = result["land_value"]["value"]
    assert land["value"] == 12000
    assert land["evidence_tier"] == "assessed_value_acquisition_scenario"
    assert land["provenance"] == "assumption"
    assert "not a sale price" in land["limitations"][0]


def test_finance_defaults_builder_keeps_market_unknown_and_produces_target_scenarios():
    cfg = {
        "assumptions": {
            "hard_cost_psf": {"value": 200, "low": 180, "high": 220, "unit": "USD/sf",
                "provenance": "assumption", "source": "hud_tdc_2024", "rationale": "Public HCC cap proxy.",
                "by_typology": {"rowhouse": {"value": 183, "low": 156, "high": 201}}},
            "steep_slope_cost_share": {"value": .12, "low": .05, "high": .30, "unit": "share",
                "provenance": "placeholder", "source": None, "rationale": "Uncalibrated placeholder."},
            "hud_tdc_multiplier": {"value": 1.75, "low": 1.75, "high": 1.75, "unit": "TDC/HCC ratio",
                "provenance": "observed", "source": "hud_tdc_2024", "rationale": "Published ratio."},
        },
        "typologies": [{"id": "rowhouse", "unit_size_sf": 1000}],
        "sources": {"sources": {
            "pwsa_rates_2026": {"name": "PWSA Rates", "publisher": "Pittsburgh Water",
                "url": "https://www.pgh2o.com/residential-commercial-customers/rates"},
            "freddie_mac_pmms": {"name": "PMMS", "publisher": "Freddie Mac",
                "url": "https://www.freddiemac.com/pmms/pmms_archives"},
            "pittsburgh_tax_rates_2026": {"name": "2026 taxes", "publisher": "Allegheny County",
                "url": "https://apps.alleghenycounty.us/website/munipgh.asp"},
            "lotline_finance_scenario_defaults": {"name": "Lotline declared planning scenario",
                "publisher": "Lotline", "url": None},
        }},
    }
    defaults = build_finance_defaults(cfg, "rowhouse")
    result = estimate_finance({"lot_area_sf": 5000, "land_value_usd": 12000}, "rowhouse", 2, 1000,
        {"county_sales": []}, defaults)
    assert result["development_cost"]["total_uses"]["value"] > 0
    assert result["for_sale"]["price_type"] == "break_even_target_price_scenario"
    assert result["for_sale"]["purchase_price"]["value"] > result["development_cost"]["per_unit_uses"]["value"]
    assert result["for_sale"]["actual_market_sale_price"]["value"] is None
    assert result["for_sale"]["buyer_monthly_cost"]["value"] > 0
    assert result["rental"]["monthly_rent_required"]["value"] > 0
    pwsa_ref = next(ref for ref in result["scenario_source_refs"].values()
                    if ref.get("url") == "https://www.pgh2o.com/residential-commercial-customers/rates")
    assert pwsa_ref["url"].startswith("https://")
    assert "hud_tdc_2024" in defaults["hud_tdc_benchmark_per_unit"]["source_ids"]
    assert defaults["soft_cost_share"]["source_ids"] == ["lotline_finance_scenario_defaults"]
    assert "not estimated from HUD TDC" in defaults["soft_cost_share"]["limitations"][0]


def test_hazard_flags_apply_placeholder_adjustment_to_site_line_item():
    defaults = base_defaults()
    defaults.pop("site_cost_usd")
    defaults["site_cost_share"] = env(.10, .10, .10, "share", "lotline_scenario")
    defaults["steep_slope_cost_share"] = {
        **env(.12, .05, .30, "share", ""), "provenance": "placeholder",
        "evidence_tier": "configured_placeholder",
        "limitations": ["Uncalibrated placeholder."],
    }
    evidence = {"county_sales": sales()}
    clear = estimate_finance({"lot_area_sf": 5000}, "rowhouse", 2, 1000, evidence, defaults)
    flagged = estimate_finance({"lot_area_sf": 5000, "steep_slope": True}, "rowhouse", 2, 1000, evidence, defaults)
    assert flagged["development_cost"]["line_items"]["site_work"]["value"] > clear["development_cost"]["line_items"]["site_work"]["value"]
    adjust = flagged["development_cost"]["hazard_site_adjustments"]["steep_slope"]
    assert adjust["provenance"] == "placeholder"
    assert flagged["development_cost"]["line_items"]["site_work"]["evidence_tier"] == "site_risk_scenario"
    assert flagged["development_cost"]["total_uses"]["provenance"] == "placeholder"
    assert flagged["rental"]["monthly_rent_required"]["provenance"] == "placeholder"
    assert any("Uncalibrated placeholder" in x for x in flagged["rental"]["monthly_rent_required"]["limitations"])
