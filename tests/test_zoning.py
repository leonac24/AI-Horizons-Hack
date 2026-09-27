from core.zoning import evaluate


def _rules(reviewed=True, status="by_right", per_unit=2000):
    """Rules for the map code TEST-M: use from base district TEST, dimensions
    from subdistrict M — the split Title Nine actually uses."""
    return {
        "districts": {"TEST": {
            "uses": {"two_unit": {"status": status, "code_section": "999.01", "quote": "q",
                                  "reviewed": reviewed}},
        }},
        "subdistricts": {"M": {
            "dimensional": {"lot_area_per_unit_sf": {"value": per_unit, "code_section": "999.02",
                                                     "quote": "q", "reviewed": True}},
        }},
    }


def _typ(cfg):
    return next(t for t in cfg.typologies if t.use_key == "two_unit")


def test_unreviewed_district_needs_review(cfg):
    r = evaluate(cfg, {}, "TEST-M", _typ(cfg), 5000, 2)
    assert r.status == "needs_review" and not r.reviewed


def test_unreviewed_use_needs_review(cfg):
    r = evaluate(cfg, _rules(reviewed=False), "TEST-M", _typ(cfg), 5000, 2)
    assert r.status == "needs_review"


def test_by_right_passes_with_citation(cfg):
    r = evaluate(cfg, _rules(), "TEST-M", _typ(cfg), 5000, 2)
    assert r.status == "by_right"
    assert r.use_citation and "999.01" in r.use_citation
    assert all(c.passed for c in r.checks)


def test_failed_dimensional_rule_means_variance(cfg):
    r = evaluate(cfg, _rules(per_unit=3000), "TEST-M", _typ(cfg), 5000, 2)
    assert r.status == "variance_needed"
    assert [c.rule_id for c in r.checks if not c.passed] == ["lot_area_per_unit_sf"]
    assert r.max_units_by_rule == 1


def test_not_permitted(cfg):
    assert evaluate(cfg, _rules(status="not_permitted"), "TEST-M", _typ(cfg), 5000, 2).status == "not_permitted"


def _with_height(value, reviewed=True):
    """Rules for a district that also caps height, in feet."""
    r = _rules()
    r["subdistricts"]["M"]["dimensional"]["max_height_ft"] = {
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

    r = evaluate(cfg, _with_height(height_ft - 5), "TEST-M", typ, 5000, 2)
    assert r.status == "variance_needed"
    failed = [c for c in r.checks if not c.passed]
    assert [c.rule_id for c in failed] == ["max_height_ft"]
    assert failed[0].actual == round(height_ft, 1)
    assert failed[0].citation and "999.03" in failed[0].citation


def test_height_rule_that_fits_stays_by_right(cfg):
    typ = _typ(cfg)
    r = evaluate(cfg, _with_height(typ.stories * typ.floor_height_ft + 5), "TEST-M", typ, 5000, 2)
    assert r.status == "by_right"
    assert all(c.passed for c in r.checks)


def test_unreviewed_height_rule_is_ignored_not_assumed(cfg):
    """An extracted-but-unreviewed rule must not decide anything. A height the
    building clearly busts is skipped until a human signs off on it."""
    typ = _typ(cfg)
    r = evaluate(cfg, _with_height(1, reviewed=False), "TEST-M", typ, 5000, 2)
    assert r.status == "by_right"
    assert "max_height_ft" not in [c.rule_id for c in r.checks]


def test_district_splits_into_base_and_subdistrict(cfg):
    """Title Nine sets use by base district and size by subdistrict, so `R1D-H`
    reads two rows. Only a declared suffix splits: UC-MU and GT-B are whole
    district names, and splitting them would look up rules that do not exist."""
    split = cfg.zoning.district_code.split
    assert split("R1D-H") == ("R1D", "H")
    assert split("RM-VL") == ("RM", "VL")
    assert split("UC-MU") == ("UC-MU", None)
    assert split("R-MU") == ("R-MU", None)
    assert split("GT-B") == ("GT-B", None)
    assert split("SP-1") == ("SP-1", None)
    assert split("H") == ("H", None)  # Hillside, a base district, not a suffix
    assert split(None) == (None, None)


def test_use_rule_is_shared_across_subdistricts(cfg):
    """One use rule on the base district answers every density under it — the
    whole point of splitting. R1D-L and R1D-VH must agree on what may be built."""
    rules = {"districts": {"R1D": {"uses": {"two_unit": {
        "status": "not_permitted", "code_section": "911.02", "quote": "q", "reviewed": True}}}},
        "subdistricts": {}}
    for code in ("R1D-L", "R1D-VH", "R1D-M"):
        assert evaluate(cfg, rules, code, _typ(cfg), 5000, 2).status == "not_permitted"


def test_dimensional_rules_without_a_subdistrict_are_absent_not_assumed(cfg):
    """A base district with no suffix (H, P, LNC) has no § 903.03 row. That must
    read as "no dimensional rule", never as a rule that happens to pass."""
    rules = {"districts": {"H": {"uses": {"two_unit": {
        "status": "by_right", "code_section": "911.02", "quote": "q", "reviewed": True}}}},
        "subdistricts": {"M": {"dimensional": {"max_height_ft": {
            "value": 1, "code_section": "903.03", "quote": "q", "reviewed": True}}}}}
    r = evaluate(cfg, rules, "H", _typ(cfg), 5000, 2)
    assert r.status == "by_right"
    assert r.checks == []


def _citywide(reviewed=True, status="not_permitted"):
    """A use Chapter 912 governs city-wide, with no row in the district table."""
    return {"districts": {"TEST": {"uses": {}}}, "subdistricts": {},
            "citywide": {"uses": {"single_unit_detached_with_adu": {
                "status": status, "code_section": "912.08", "quote": "q",
                "note": "overlay never adopted", "reviewed": reviewed}}}}


def _adu_typ(cfg):
    return next(t for t in cfg.typologies if t.use_key == "single_unit_detached_with_adu")


def test_citywide_use_decides_without_a_district_row(cfg):
    """ADU is not a column in the Chapter 911 use table, so a district lookup can
    never answer it. A reviewed city-wide rule answers it instead, and a
    prohibition disqualifies the scenario rather than merely scoring it low."""
    r = evaluate(cfg, _citywide(), "TEST-M", _adu_typ(cfg), 5000, 2)
    assert r.status == "not_permitted"
    assert r.disqualified
    assert r.use_citation and "912.08" in r.use_citation
    assert r.note and "overlay" in r.note


def test_citywide_use_applies_in_every_district(cfg):
    for code in ("TEST-M", "R1D-H", "H", "UC-MU"):
        assert evaluate(cfg, _citywide(), code, _adu_typ(cfg), 5000, 2).status == "not_permitted"


def test_unreviewed_citywide_use_decides_nothing(cfg):
    """The human-in-the-loop rule holds here too: until a person signs off, a
    city-wide rule must not disqualify anything."""
    r = evaluate(cfg, _citywide(reviewed=False), "TEST-M", _adu_typ(cfg), 5000, 2)
    assert r.status == "needs_review"
    assert not r.disqualified


def test_citywide_use_does_not_shadow_other_typologies(cfg):
    """Only the use_key named city-wide is affected; everything else still reads
    from the district table."""
    rules = _citywide()
    rules["districts"]["TEST"]["uses"]["two_unit"] = {
        "status": "by_right", "code_section": "911.02", "quote": "q", "reviewed": True}
    assert evaluate(cfg, rules, "TEST-M", _typ(cfg), 5000, 2).status == "by_right"


def test_shipped_adu_rule_quote_is_verbatim_in_the_saved_code_text(cfg):
    """A rule's quote is its evidence. If the ADU rule's quote is not in the
    § 912.08 text we saved, the rule is not sourced and must not ship."""
    import re
    from pathlib import Path

    import yaml

    from core.config import ROOT

    doc = yaml.safe_load((ROOT / cfg.zoning.rules_file).read_text(encoding="utf-8")) or {}
    rule = ((doc.get("citywide") or {}).get("uses") or {}).get("single_unit_detached_with_adu")
    if rule is None:
        return  # rule not shipped; nothing to verify
    src = Path(ROOT / cfg.zoning.code.raw_text_dir) / "912.txt"
    if not src.exists():
        return  # raw text is gitignored on a fresh clone
    norm = lambda s: re.sub(r"\s+", " ", s).strip().lower()
    assert len(rule["quote"].split()) < 25
    assert norm(rule["quote"]) in norm(src.read_text(encoding="utf-8"))


def test_citation_renders_a_real_section_sign(cfg):
    """zoning.yaml's citation_format was double-encoded (\xc3\x82\xc2\xa7 rather
    than \xc2\xa7), so every citation the UI shows read "Pittsburgh Code Â§".
    AnalysisPanel renders use_citation directly, so this was on screen."""
    from core.zoning import cite

    assert "Â§" not in cite(cfg, "903.03.B")
    assert "§ 903.03.B" in cite(cfg, "903.03.B")
