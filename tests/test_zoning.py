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


def _with_height(value, reviewed=True):
    """Rules for a district that also caps height, in feet."""
    r = _rules()
    r["TEST-D"]["dimensional"]["max_height_ft"] = {
        "value": value, "code_section": "999.03", "quote": "q", "reviewed": reviewed}
    return r


def test_height_rule_is_checked_in_feet(cfg):
    """The code caps height in feet; a typology is described in stories.

    This branch used to be `continue` in core/zoning.py, so a district could cap
    height at 20 ft and a five-storey building still came back by-right. The
    rule was extracted and stored, just never applied. The conversion is
    stories * floor_height_ft, both from typologies.yaml.
    """
    typ = _typ(cfg)
    height_ft = typ.stories * typ.floor_height_ft

    r = evaluate(cfg, _with_height(height_ft - 5), "TEST-D", typ, 5000, 2)
    assert r.status == "variance_needed"
    failed = [c for c in r.checks if not c.passed]
    assert [c.rule_id for c in failed] == ["max_height_ft"]
    assert failed[0].actual == round(height_ft, 1)
    assert failed[0].citation and "999.03" in failed[0].citation


def test_height_rule_that_fits_stays_by_right(cfg):
    typ = _typ(cfg)
    r = evaluate(cfg, _with_height(typ.stories * typ.floor_height_ft + 5), "TEST-D", typ, 5000, 2)
    assert r.status == "by_right"
    assert all(c.passed for c in r.checks)


def test_unreviewed_height_rule_is_ignored_not_assumed(cfg):
    """An extracted-but-unreviewed rule must not decide anything. A height the
    building clearly busts is skipped until a human signs off on it."""
    typ = _typ(cfg)
    r = evaluate(cfg, _with_height(1, reviewed=False), "TEST-D", typ, 5000, 2)
    assert r.status == "by_right"
    assert "max_height_ft" not in [c.rule_id for c in r.checks]


def test_citation_renders_a_real_section_sign(cfg):
    """zoning.yaml's citation_format was double-encoded (\xc3\x82\xc2\xa7 rather
    than \xc2\xa7), so every citation the UI shows read "Pittsburgh Code Â§".
    AnalysisPanel renders use_citation directly, so this was on screen."""
    from core.zoning import cite

    assert "Â§" not in cite(cfg, "903.03.B")
    assert "§ 903.03.B" in cite(cfg, "903.03.B")
