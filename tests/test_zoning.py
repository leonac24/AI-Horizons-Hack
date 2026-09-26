from core.zoning import evaluate


def _rules(reviewed=True, status="by_right", per_unit=2000):
    return {"TEST-D": {
        "uses": {"two_unit": {"status": status, "code_section": "999.01", "quote": "q", "reviewed": reviewed}},
        "dimensional": {"lot_area_per_unit_sf": {"value": per_unit, "code_section": "999.02", "quote": "q",
                                                  "reviewed": True}},
    }}


def _typ(cfg):
    return next(t for t in cfg.typologies if t.use_key == "two_unit")


def test_unreviewed_district_needs_review(cfg):
    r = evaluate(cfg, {}, "TEST-D", _typ(cfg), 5000, 2)
    assert r.status == "needs_review" and not r.reviewed


def test_unreviewed_use_needs_review(cfg):
    r = evaluate(cfg, _rules(reviewed=False), "TEST-D", _typ(cfg), 5000, 2)
    assert r.status == "needs_review"


def test_by_right_passes_with_citation(cfg):
    r = evaluate(cfg, _rules(), "TEST-D", _typ(cfg), 5000, 2)
    assert r.status == "by_right"
    assert r.use_citation and "999.01" in r.use_citation
    assert all(c.passed for c in r.checks)


def test_failed_dimensional_rule_means_variance(cfg):
    r = evaluate(cfg, _rules(per_unit=3000), "TEST-D", _typ(cfg), 5000, 2)
    assert r.status == "variance_needed"
    assert [c.rule_id for c in r.checks if not c.passed] == ["lot_area_per_unit_sf"]
    assert r.max_units_by_rule == 1


def test_not_permitted(cfg):
    assert evaluate(cfg, _rules(status="not_permitted"), "TEST-D", _typ(cfg), 5000, 2).status == "not_permitted"
