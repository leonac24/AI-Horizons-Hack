"""Zoning facts: verbatim-quote verification, expansion onto districts, and the
engine features they need (width-conditional uses, setbacks)."""

import copy

import pytest
import yaml

from core.engine import LotShape, pure_buildings
from core.zoning import buildable_margins, evaluate
from pipeline.zoning.build_rules import FACTS, FactError, expand, verify


@pytest.fixture(scope="module")
def facts():
    return yaml.safe_load(FACTS.read_text(encoding="utf-8"))


def test_every_committed_quote_is_verbatim_and_short(facts):
    verify(facts)  # raises on any miss


def test_a_misquote_is_rejected(facts):
    bad = copy.deepcopy(facts)
    bad["use_facts"][0]["quotes"] = ["Single-Unit Detached Residential means anything you like."]
    with pytest.raises(FactError, match="not found verbatim"):
        verify(bad)


def test_family_and_density_fan_out(facts):
    rules = expand(facts, ["R2-L", "RM-M", "H", "LNC"])
    # Uses sit on the base district, size rules on the family-specific subdistrict.
    assert set(rules["districts"]) == {"R2", "RM", "H"}  # LNC not extracted yet
    assert set(rules["subdistricts"]) == {"R2-L", "RM-M"}
    assert rules["districts"]["R2"]["uses"]["two_unit"]["status"] == "by_right"
    assert rules["districts"]["R2"]["uses"]["multi_unit"]["status"] == "not_permitted"
    assert rules["subdistricts"]["R2-L"]["dimensional"]["min_lot_area_sf"]["value"] == 3000
    assert rules["subdistricts"]["RM-M"]["dimensional"]["max_stories"]["value"] == 4
    assert rules["districts"]["H"]["uses"]["single_unit_detached"]["status"] == "administrator_exception"
    assert rules["districts"]["H"]["dimensional"]["min_lot_area_sf"]["value"] == 3200  # § 905.02, no suffix
    # expand() copies each fact's reviewed flag through; it never invents one.
    # Asserting "all unreviewed" instead would only hold until someone ticks a
    # box in REVIEW.md, which is the point of the file.
    by_use_key = {f["use_key"]: f for f in facts["use_facts"]}
    for use_key, rule in rules["districts"]["R2"]["uses"].items():
        assert rule["reviewed"] == bool(by_use_key[use_key].get("reviewed"))


def test_family_specific_subdistrict_overrides_generic(cfg, facts):
    """RM-H and R1D-H share the H suffix but not their height limit."""
    from core.zoning import dimensional_rules
    rules = expand(facts, ["R1D-H", "RM-H"])
    rules["subdistricts"]["H"] = {"dimensional": {"max_height_ft": {"value": 1, "reviewed": False}}}
    assert dimensional_rules(cfg, rules, "RM-H")["max_height_ft"]["value"] == 85
    assert dimensional_rules(cfg, rules, "R1D-H")["max_height_ft"]["value"] == 40
    assert dimensional_rules(cfg, rules, "R3-H")["max_height_ft"]["value"] == 1  # generic entry only


def _reviewed(rule):
    return {**rule, "reviewed": True}


def _typ(cfg, use_key):
    return next(t for t in cfg.typologies if t.use_key == use_key)


def test_width_conditional_use_needs_observed_frontage(cfg, facts):
    rules = expand(facts, ["R1D-M"])
    uses = rules["districts"]["R1D"]["uses"]
    uses["single_unit_attached"] = _reviewed(uses["single_unit_attached"])
    typ = _typ(cfg, "single_unit_attached")
    narrow = evaluate(cfg, rules, "R1D-M", typ, 4000, 2, frontage_ft=30)
    wide = evaluate(cfg, rules, "R1D-M", typ, 4000, 2, frontage_ft=50)
    unknown = evaluate(cfg, rules, "R1D-M", typ, 4000, 2, frontage_ft=None)
    assert narrow.status == "by_right"
    assert wide.status == "special_exception"
    assert unknown.status == cfg.zoning.status_id("unreviewed") and "width" in (unknown.note or "")


def test_reviewed_setbacks_are_reported_not_scored(cfg, facts):
    rules = expand(facts, ["R2-L"])
    uses = rules["districts"]["R2"]["uses"]
    uses["two_unit"] = _reviewed(uses["two_unit"])
    dims = rules["subdistricts"]["R2-L"]["dimensional"]
    for k in dims:
        dims[k] = _reviewed(dims[k])
    r = evaluate(cfg, rules, "R2-L", _typ(cfg, "two_unit"), 4000, 2, frontage_ft=40)
    assert r.setbacks["front_setback_ft"].value_ft == 30
    assert r.setbacks["interior_side_setback_ft"].value_ft == 5
    assert all(c.rule_id not in r.setbacks for c in r.checks)
    assert r.status == "by_right"


def test_options_are_sized_to_the_buildable_area_once_setbacks_are_reviewed(cfg, strict_cfg, facts):
    rules = expand(facts, ["R2-L"])
    assert buildable_margins(strict_cfg, rules, "R2-L") == {}  # unreviewed setbacks change nothing when review is required
    d = rules["subdistricts"]["R2-L"]["dimensional"]
    for k in d:
        d[k] = _reviewed(d[k])
    m = buildable_margins(cfg, rules, "R2-L")
    assert m["left"] == m["right"] == 5
    typ = cfg.typologies[0]
    w, depth = typ.building.footprint_ft
    typ = typ.model_copy(update={"building": typ.building.model_copy(update={"max_in_a_row": 9})})
    # Two buildings fit the raw frontage, but only one fits between the side setbacks.
    frontage = 2 * w + 1
    shape = LotShape(frontage_ft=frontage, depth_ft=depth + m["front"] + m["rear"] + 1,
                     provenance="observed", sourceIds=[], note="")
    area = 10 * typ.min_lot_sf_for_form + 1
    assert pure_buildings(typ, shape, area)[0] == 2
    assert pure_buildings(typ, shape, area, m) == (1, True)


def test_party_wall_forms_skip_side_yards(cfg):
    """§ 903.03(c): an attached home has no interior side yard on the party-wall
    side, so side setbacks must not squeeze a rowhouse off a narrow lot."""
    attached = next(t for t in cfg.typologies if t.building.party_walls)
    w, depth = attached.building.footprint_ft
    shape = LotShape(frontage_ft=w + 1, depth_ft=depth + 60, provenance="observed", sourceIds=[], note="")
    m = {"front": 15, "rear": 15, "left": 5, "right": 5}
    area = attached.min_lot_sf_for_form + 1
    assert pure_buildings(attached, shape, area, m)[1]
    detached = attached.model_copy(update={"building": attached.building.model_copy(update={"party_walls": False})})
    assert not pure_buildings(detached, shape, area, m)[1]
