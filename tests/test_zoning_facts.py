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
    assert set(rules) == {"R2-L", "RM-M", "H"}  # LNC not extracted yet
    assert rules["R2-L"]["uses"]["two_unit"]["status"] == "by_right"
    assert rules["R2-L"]["uses"]["multi_unit"]["status"] == "not_permitted"
    assert rules["R2-L"]["dimensional"]["min_lot_area_sf"]["value"] == 3000
    assert rules["RM-M"]["dimensional"]["max_stories"]["value"] == 4
    assert rules["H"]["uses"]["single_unit_detached"]["status"] == "administrator_exception"
    assert all(not r["reviewed"] for r in rules["R2-L"]["uses"].values())  # nothing reviewed by default


def _reviewed(rule):
    return {**rule, "reviewed": True}


def _typ(cfg, use_key):
    return next(t for t in cfg.typologies if t.use_key == use_key)


def test_width_conditional_use_needs_observed_frontage(cfg, facts):
    rules = expand(facts, ["R1D-M"])
    rules["R1D-M"]["uses"]["single_unit_attached"] = _reviewed(rules["R1D-M"]["uses"]["single_unit_attached"])
    typ = _typ(cfg, "single_unit_attached")
    narrow = evaluate(cfg, rules, "R1D-M", typ, 4000, 2, frontage_ft=30)
    wide = evaluate(cfg, rules, "R1D-M", typ, 4000, 2, frontage_ft=50)
    unknown = evaluate(cfg, rules, "R1D-M", typ, 4000, 2, frontage_ft=None)
    assert narrow.status == "by_right"
    assert wide.status == "special_exception"
    assert unknown.status == cfg.zoning.status_id("unreviewed") and "width" in (unknown.note or "")


def test_reviewed_setbacks_are_reported_not_scored(cfg, facts):
    rules = expand(facts, ["R2-L"])
    d = rules["R2-L"]
    d["uses"]["two_unit"] = _reviewed(d["uses"]["two_unit"])
    for k in d["dimensional"]:
        d["dimensional"][k] = _reviewed(d["dimensional"][k])
    r = evaluate(cfg, rules, "R2-L", _typ(cfg, "two_unit"), 4000, 2, frontage_ft=40)
    assert r.setbacks["front_setback_ft"].value_ft == 30
    assert r.setbacks["interior_side_setback_ft"].value_ft == 5
    assert all(c.rule_id not in r.setbacks for c in r.checks)
    assert r.status == "by_right"


def test_options_are_sized_to_the_buildable_area_once_setbacks_are_reviewed(cfg, facts):
    rules = expand(facts, ["R2-L"])
    assert buildable_margins(cfg, rules, "R2-L") == {}  # unreviewed setbacks change nothing
    d = rules["R2-L"]["dimensional"]
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
