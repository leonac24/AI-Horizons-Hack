"""The work plan: what to go and find out about one parcel.

Lotline may not say what to build, so the actionable thing it *can* say is what is
still unknown and who answers it. These tests pin the two properties that make
that trustworthy: a question is derived from the arithmetic rather than written
down beside it, and the illustrative cost figures can never reorder the list.
"""

import json
import random

import pytest

from core.config import ROOT, ConfigError, load_config
from core.engine import analyze
from core.inquiries import build
from core.metrics import Samples

_LOCAL_INCOME = "tract_median_household_income"


def _reviewed_rules(cfg, use_key, per_unit):
    """Use from the base district, dimensions from the subdistrict — the split
    Title Nine actually uses, as in tests/test_zoning.py."""
    permitted = next(i for i, s in cfg.zoning.statuses.items() if s.role == "permitted")
    return {
        "districts": {"TEST": {"uses": {
            use_key: {"status": permitted, "reviewed": True,
                      "code_section": "911.01", "quote": "q"}}}},
        "subdistricts": {"M": {"dimensional": {
            "lot_area_per_unit_sf": {"value": per_unit, "reviewed": True,
                                     "code_section": "911.02", "quote": "q"}}}},
    }


# The fixture lot sits in TEST-D, and D is not one of the subdistrict suffixes
# zoning.yaml recognises, so a dimensional rule would never be looked up. Tests
# that need reviewed dimensions use TEST-M, as tests/test_zoning.py does.
def _in_subdistrict(lot):
    return {**lot, "zoning": "TEST-M"}


def _use_rules(monkeypatch, rules):
    import core.engine as engine_mod
    import core.zoning as zoning_mod
    for mod in (zoning_mod, engine_mod):
        monkeypatch.setattr(mod, "load_rules", lambda cfg, r=rules: r)


def _metric_on(analysis, key):
    """The one site-context metric resting on exactly `key`."""
    return next(m for m in analysis.site_context if m.dependsOn == [key])


# --- attribution ---------------------------------------------------------------
def test_metrics_declare_the_assumptions_they_rest_on(cfg, lot):
    """dependsOn is recorded by the engine as it computes, so a question can never
    drift away from the number it is about."""
    a = analyze(cfg, lot)
    metrics = [m for s in a.scenarios for m in s.metrics.values()]
    assert any(m.dependsOn for m in metrics), "no metric recorded a dependency"
    for m in metrics + a.site_context:
        for key in m.dependsOn:
            assert key in cfg.assumptions, f"{m.id} depends on unknown assumption {key!r}"


def test_a_plan_inherits_the_dependencies_of_its_building_types(cfg, lot):
    from core.plan import Placement, analyze_plan
    typ = cfg.typologies[0]
    r = analyze_plan(cfg, lot, [Placement(typology_id=typ.id, count=1)])
    assert any(m.dependsOn for m in r.metrics.values())


# --- coverage ------------------------------------------------------------------
def test_every_open_assumption_behind_a_metric_becomes_a_question(cfg, lot):
    a = analyze(cfg, lot)
    used = {k for m in [*a.site_context, *(m for s in a.scenarios for m in s.metrics.values())]
            for k in m.dependsOn}
    open_keys = {k for k in used
                 if cfg.assumptions[k].high > cfg.assumptions[k].low
                 or cfg.assumptions[k].provenance == "placeholder"}
    asked = {q.id for q in build(cfg, a)}
    # The zoning score is claimed by the zoning question rather than listed
    # separately as a bare number to go and look up.
    claimed = {q.id for q in build(cfg, a) if q.kind == "zoning_use"}
    missing = open_keys - asked - {"zoning_status_score"}
    assert not missing, f"open but never asked about: {sorted(missing)} (asked: {sorted(claimed)})"


def test_settled_conventions_are_not_presented_as_unknowns(cfg, lot):
    """A zero-width `assumption` is a declared modelling choice. Asking someone to
    go and find out the cost-burden threshold would be noise."""
    asked = {q.id for q in build(cfg, analyze(cfg, lot))}
    for key, asm in cfg.assumptions.items():
        if asm.provenance == "assumption" and asm.high == asm.low:
            assert key not in asked, f"{key} is a convention, not a question"


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_random_parcels_all_produce_a_usable_work_plan(cfg, seed):
    """Coverage in the spirit of the citywide rule: placeholders are fine, crashes
    and half-rendered templates are not."""
    path = ROOT / "data" / "processed" / "parcels.json"
    if not path.exists():
        pytest.skip("no parcel index built")
    parcels = list(json.loads(path.read_text(encoding="utf-8"))["parcels"].values())
    random.seed(seed)
    for p in random.sample(parcels, 12):
        qs = build(cfg, analyze(cfg, p))
        assert qs, f"{p['id']} produced no questions at all"
        for q in qs:
            for field in (q.question, q.why, q.ask_for, q.contact_template):
                assert "{" not in field, f"{q.id}: unfilled template in {field[:60]!r}"
            assert q.resolver_label and q.effort_label


# --- ordering ------------------------------------------------------------------
def test_availability_and_legality_outrank_every_number(cfg, lot):
    """No point pricing a lot you cannot buy or a use you will not be granted."""
    qs = build(cfg, analyze(cfg, {**lot, "public": True}))
    assert qs[0].kind == "public_parcel" and qs[0].blocks_eligibility
    assert qs[1].kind == "zoning_use" and qs[1].blocks_eligibility
    assert all(not q.blocks_eligibility for q in qs[2:])


def test_a_private_lot_is_not_asked_about_disposition(cfg, lot):
    kinds = {q.kind for q in build(cfg, analyze(cfg, {**lot, "public": False}))}
    assert "public_parcel" not in kinds


def test_illustrative_costs_cannot_reorder_the_work_plan(config_copy, lot):
    """The punchline is "do this one first". Ordering is by what can change the
    answer, never by a cost figure we had to invent."""
    d, edit = config_copy
    cfg1 = load_config(d)
    before = [q.id for q in build(cfg1, analyze(cfg1, lot))]

    def zero_costs(y):
        for rec in [*y["inquiries"].values(), y["generic"]]:
            for field in ("cost", "weeks"):
                if rec.get(field):
                    rec[field] = {"low": 0, "high": 0, "unit": rec[field]["unit"]}

    edit("inquiries.yaml", zero_costs)
    cfg2 = load_config(d)
    assert [q.id for q in build(cfg2, analyze(cfg2, lot))] == before


def test_cost_and_timing_are_always_labelled_placeholders(cfg, lot):
    for q in build(cfg, analyze(cfg, lot)):
        for money in (q.cost, q.weeks):
            if money is not None:
                assert money.provenance == "placeholder"


# --- zoning questions ----------------------------------------------------------
def test_unreviewed_use_is_asked_once_for_the_district(cfg, lot):
    qs = [q for q in build(cfg, analyze(cfg, lot)) if q.kind == "zoning_use"]
    assert len(qs) == 1
    assert lot["zoning"] in qs[0].question or lot["zoning"] in qs[0].why
    assert qs[0].blocks_eligibility


def test_a_failed_dimensional_rule_becomes_a_variance_question(cfg, lot, monkeypatch):
    typ = cfg.typologies[0]
    _use_rules(monkeypatch, _reviewed_rules(cfg, typ.use_key, per_unit=10_000_000))
    dim = [q for q in build(cfg, analyze(cfg, _in_subdistrict(lot)))
           if q.kind == "zoning_dimensional"]
    assert dim, "a rule this lot fails produced no question"
    assert dim[0].citation, "a variance question must carry its Title Nine citation"
    # A variance is a path, not a bar: needing one never excludes an option.
    assert not dim[0].blocks_eligibility


def test_a_reviewed_district_stops_asking_about_use(cfg, lot, monkeypatch):
    typ = cfg.typologies[0]
    _use_rules(monkeypatch, _reviewed_rules(cfg, typ.use_key, per_unit=1))
    a = analyze(cfg, _in_subdistrict(lot))
    reviewed = [s for s in a.scenarios if s.zoning.reviewed]
    assert reviewed, "the rules fixture did not take effect"
    if len(reviewed) == len(a.scenarios):
        assert not [q for q in build(cfg, a) if q.kind == "zoning_use"]


# --- lot shape -----------------------------------------------------------------
def test_a_drawn_lot_shape_is_asked_about(cfg, lot):
    a = analyze(cfg, lot)
    assert a.lot_shape.provenance == "placeholder"  # the fixture lot has no legal dims
    assert any(q.kind == "lot_shape" for q in build(cfg, a))


def test_a_surveyed_lot_shape_is_not(cfg, lot):
    a = analyze(cfg, {**lot, "frontage_ft": 40, "depth_ft": 125})
    assert a.lot_shape.provenance == "observed"
    assert not any(q.kind == "lot_shape" for q in build(cfg, a))


# --- degrading rather than dropping --------------------------------------------
def test_an_assumption_with_no_record_still_becomes_a_question(config_copy, lot):
    """A newly added assumption must show up as a real question instead of
    silently vanishing from the work plan."""
    d, edit = config_copy
    target = "hard_cost_psf"

    def drop(y):
        del y["inquiries"][target]

    edit("inquiries.yaml", drop)
    cfg2 = load_config(d)
    q = next(q for q in build(cfg2, analyze(cfg2, lot)) if q.id == target)
    assert q.matched is False
    assert q.resolver == cfg2.inquiries.generic.resolver
    assert "{" not in q.why
    assert target.replace("_", " ") in q.question


# --- answers -------------------------------------------------------------------
def test_an_answer_collapses_the_band_it_replaces(cfg, lot):
    """The loop that makes this a tool rather than a report: an answer arrives, the
    band becomes a point, and the ranking can move."""
    wide = _metric_on(analyze(cfg, lot), _LOCAL_INCOME)
    assert wide.high > wide.low

    answered = analyze(cfg, lot, Samples(cfg, overrides={_LOCAL_INCOME: 57_500}))
    m = next(m for m in answered.site_context if m.id == wide.id)
    assert m.value == m.low == m.high == 57_500


def test_an_answer_does_not_upgrade_provenance(cfg, lot):
    """The user asserted it; we did not verify it. The API echoes overrides so the
    UI can label them, but a claim must never read as observed evidence."""
    before = _metric_on(analyze(cfg, lot), _LOCAL_INCOME)
    after_analysis = analyze(cfg, lot, Samples(cfg, overrides={_LOCAL_INCOME: 57_500}))
    after = next(m for m in after_analysis.site_context if m.id == before.id)
    assert after.provenance == before.provenance


def test_an_unrelated_metric_is_untouched_by_an_answer(cfg, lot):
    """Each assumption draws from its own seeded stream, so pinning one must not
    reshuffle any other."""
    base = analyze(cfg, lot)
    answered = analyze(cfg, lot, Samples(cfg, overrides={_LOCAL_INCOME: 57_500}))
    for b in base.site_context:
        if _LOCAL_INCOME in b.dependsOn:
            continue
        a = next(m for m in answered.site_context if m.id == b.id)
        assert (a.value, a.low, a.high) == (b.value, b.low, b.high), b.id


# --- nothing enumerated in code ------------------------------------------------
def test_fake_typologies_still_produce_questions(config_copy, lot):
    d, edit = config_copy

    def fake(y):
        y["typologies"] = [
            {"id": "zeta", "label": "Zeta", "short_label": "Z", "color": "#000000",
             "use_key": "multi_unit", "unit_size_sf": 900, "stories": 3, "floor_height_ft": 11,
             "tenure_default": "renter",
             "building": {"footprint_ft": [20, 50], "homes": 6, "massing": "walkup",
                          "body": "#111111", "roof": "#222222", "max_in_a_row": 3}},
        ]

    def strip(y):
        for a in y["assumptions"].values():
            a.pop("by_typology", None)

    edit("typologies.yaml", fake)
    edit("assumptions.yaml", strip)
    cfg2 = load_config(d)
    assert build(cfg2, analyze(cfg2, lot))


# --- config validation ---------------------------------------------------------
@pytest.mark.parametrize("field,value,match", [
    ("resolver", "nobody", "resolver"),
    ("effort", "sometime", "effort"),
    ("pins", "no_such_assumption", "pins"),
])
def test_config_rejects_a_dangling_inquiry_pointer(config_copy, field, value, match):
    """A dangling pointer here would not crash anything — the work plan would just
    quietly drop a question — so it has to fail at startup."""
    d, edit = config_copy

    def break_one(y):
        next(iter(y["inquiries"].values()))[field] = value

    edit("inquiries.yaml", break_one)
    with pytest.raises(ConfigError, match=match):
        load_config(d)


def test_config_requires_exactly_one_record_per_required_role(config_copy):
    d, edit = config_copy

    def duplicate(y):
        rec = dict(next(r for r in y["inquiries"].values() if r["trigger"] == "zoning_use"))
        y["inquiries"]["second_use_question"] = rec

    edit("inquiries.yaml", duplicate)
    with pytest.raises(ConfigError, match="zoning_use"):
        load_config(d)


def test_config_rejects_a_dimensional_record_naming_no_rule(config_copy):
    d, edit = config_copy

    def bogus(y):
        y["inquiries"]["not_a_rule"] = dict(
            next(r for r in y["inquiries"].values() if r["trigger"] == "zoning_dimensional"))

    edit("inquiries.yaml", bogus)
    with pytest.raises(ConfigError, match="not_a_rule"):
        load_config(d)


def test_cost_range_rejects_a_backwards_band(config_copy):
    d, edit = config_copy

    def flip(y):
        rec = next(r for r in y["inquiries"].values() if r.get("cost"))
        rec["cost"] = {"low": 9000, "high": 100, "unit": "USD"}

    edit("inquiries.yaml", flip)
    with pytest.raises(ConfigError):
        load_config(d)
