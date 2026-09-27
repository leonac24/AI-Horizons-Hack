"""Tax in the evidence layer. Spec: docs/superpowers/specs/2026-09-26-tax-metrics-design.md."""

import pytest

from core.config import ConfigError, load_config


def test_real_config_loads_tax_and_tension_flags(cfg):
    assert cfg.tax.taxing_bodies and cfg.tax.abatements and cfg.tax.comps.use_classes
    assert cfg.tension_flags, "criteria.yaml should declare at least one tension flag"
    assert any(c.metric_id == "revenue.public_horizon" for c in cfg.criteria)
    assert all(t.assessment_use_classes for t in cfg.typologies)


def test_config_rejects_unknown_assessment_use_class(config_copy):
    d, edit = config_copy
    edit("typologies.yaml", lambda y: y["typologies"][0].__setitem__("assessment_use_classes", ["NOT A CLASS"]))
    with pytest.raises(ConfigError, match="assessment use class"):
        load_config(d)


def test_config_rejects_tension_flag_on_unknown_criterion(config_copy):
    d, edit = config_copy
    edit("criteria.yaml", lambda y: y["tension_flags"][0].__setitem__("top_on", "nope"))
    with pytest.raises(ConfigError, match="tension_flag"):
        load_config(d)


def test_config_rejects_millage_pointing_at_unknown_assumption(config_copy):
    d, edit = config_copy
    edit("tax.yaml", lambda y: y["taxing_bodies"][0].__setitem__("millage", "nope"))
    with pytest.raises(ConfigError, match="unknown assumption"):
        load_config(d)


def test_public_config_hides_the_comps_file_path(cfg):
    assert "file" not in cfg.public_json()["tax"]["comps"]


# --- per-home assessed value ----------------------------------------------------
import core.engine as engine_mod
from core.engine import analyze
from core.metrics import Samples
from core.tax import per_home_assessed, scenario_tax

REVENUE = "revenue.public_horizon"
STABILIZED = "revenue.annual_stabilized"
HOME_TAX = "tax.per_home_monthly"


def _comps(cfg, value=50000, low=40000, high=60000, hoods=("Test",)):
    """A comps table with the same row for every typology."""
    row = {"value": value, "low": low, "high": high, "n": 99}
    return {"by_typology": {t.id: {"citywide": dict(row), "neighborhoods": {h: dict(row) for h in hoods}}
                            for t in cfg.typologies}}


def _pin(y, key, value):
    y["assumptions"][key].update(value=value, low=value, high=value)


def test_comps_fallback_order_neighborhood_citywide_placeholder(cfg):
    S = Samples(cfg)
    typ = cfg.typologies[0]
    table = _comps(cfg, 70000, 60000, 80000, hoods=("Here",))
    hood = per_home_assessed(cfg, S, typ, "Here", table)
    assert hood.provenance == "observed" and hood.note is None and hood.draws[0] == 70000
    assert 60000 <= hood.draws[1:].min() and hood.draws[1:].max() <= 80000
    city = per_home_assessed(cfg, S, typ, "Elsewhere", table)
    assert city.provenance == "observed" and "citywide" in (city.note or "")
    none = per_home_assessed(cfg, S, typ, "Here", {})
    assert none.provenance == "placeholder"
    assert none.draws[0] == cfg.assumption("assessed_building_value_per_home").for_typology(typ.id).value


# --- scenario tax, revenue series, site context ----------------------------------
def test_every_scenario_has_tax_metrics_and_a_revenue_series(cfg, lot):
    a = analyze(cfg, lot)
    for s in a.scenarios:
        for mid in (REVENUE, STABILIZED, HOME_TAX):
            m = s.metrics[mid]
            assert m.low <= m.value <= m.high and m.value >= 0, (s.typology_id, mid)
        assert len(s.revenue.years) == len(s.carbon.years)
        assert s.revenue.value[0] == 0
        assert s.revenue.value[-1] == pytest.approx(s.metrics[REVENUE].value, abs=1)
    assert {"site.tax_status_today", "site.tax_today"} <= {m.id for m in a.site_context}


def test_unreviewed_abatement_is_not_applied_and_marks_revenue_placeholder(cfg, lot):
    assert any(not a.reviewed for a in cfg.tax.abatements), "assumes the shipped program is unreviewed"
    a = analyze(cfg, lot)
    years = int(cfg.assumption("analysis_years").value)
    for s in a.scenarios:
        assert s.metrics[REVENUE].provenance == "placeholder"
        assert s.revenue.abated_years == 0
        assert s.metrics[REVENUE].value == pytest.approx(years * s.metrics[STABILIZED].value, rel=1e-3)


def _review_and_pin(edit, years_value, homestead=0):
    def review(y):
        for p in y["abatements"]:
            p.update(reviewed=True, code_section="999.99", quote="test quote")
    edit("tax.yaml", review)

    def pin(y):
        _pin(y, "abatement_years", years_value)
        _pin(y, "abatement_exempt_assessed_cap_usd", 1e9)  # cap never binds
        for key in list(y["assumptions"]):
            if key.startswith("millage_"):
                _pin(y, key, y["assumptions"][key]["value"])
            if key.startswith("homestead_exclusion_"):
                _pin(y, key, homestead)
    edit("assumptions.yaml", pin)


def test_reviewed_abatement_removes_exactly_the_abated_amount(config_copy, lot, monkeypatch):
    d, edit = config_copy
    _review_and_pin(edit, years_value=10)
    cfg = load_config(d)
    monkeypatch.setattr(engine_mod, "load_comps", lambda _cfg: _comps(cfg, 50000, 50000, 50000))
    a = analyze(cfg, lot)
    mills = sum(cfg.assumption(b.millage).value for b in cfg.tax.taxing_bodies)
    years = int(cfg.assumption("analysis_years").value)
    for s in a.scenarios:
        gross = years * s.metrics[STABILIZED].value
        abated = 10 * s.units * 50000 * mills / 1000  # building value only; land stays taxed
        assert s.revenue.abated_years == 10
        assert s.metrics[REVENUE].value == pytest.approx(gross - abated, rel=1e-3)


def test_zero_year_abatement_changes_nothing(config_copy, lot, monkeypatch):
    d, edit = config_copy
    _review_and_pin(edit, years_value=0)
    cfg = load_config(d)
    monkeypatch.setattr(engine_mod, "load_comps", lambda _cfg: _comps(cfg))
    a = analyze(cfg, lot)
    years = int(cfg.assumption("analysis_years").value)
    for s in a.scenarios:
        assert s.revenue.abated_years == 0
        assert s.metrics[REVENUE].value == pytest.approx(years * s.metrics[STABILIZED].value, rel=1e-3)


def test_exempt_parcel_pays_nothing_today_and_still_analyzes(cfg, lot):
    a = analyze(cfg, {**lot, "tax_status": cfg.tax.status.exempt_values[0]})
    today = next(m for m in a.site_context if m.id == "site.tax_today")
    status = next(m for m in a.site_context if m.id == "site.tax_status_today")
    assert today.value == 0 and status.value == 0 and status.provenance == "observed"
    assert len(a.scenarios) == len(cfg.typologies)
    unknown = next(m for m in analyze(cfg, lot).site_context if m.id == "site.tax_status_today")
    assert unknown.provenance == "placeholder"


def test_household_tax_is_inside_monthly_cost(cfg, lot):
    a = analyze(cfg, lot)
    cap = cfg.assumption("annual_capital_cost_share").value
    opex = cfg.assumption("operating_cost_per_unit_month").value
    for s in a.scenarios:
        m = s.metrics
        expected = m["affordability.dev_cost_per_unit"].value * cap / 12 + opex + m[HOME_TAX].value
        assert m["affordability.monthly_cost"].value == pytest.approx(expected, abs=2)


def test_homestead_exclusion_applies_to_owner_tenure_only(config_copy, lot):
    d, edit = config_copy
    edit("assumptions.yaml",
         lambda y: [_pin(y, k, 20000) for k in list(y["assumptions"]) if k.startswith("homestead_exclusion_")])
    cfg = load_config(d)
    S = Samples(cfg)
    typ = cfg.typologies[0]
    comps = _comps(cfg, 50000, 50000, 50000)
    owner = scenario_tax(cfg, S, typ.model_copy(update={"tenure_default": "owner"}), 2, lot, comps)
    renter = scenario_tax(cfg, S, typ.model_copy(update={"tenure_default": "renter"}), 2, lot, comps)
    assert owner.metrics[HOME_TAX].value < renter.metrics[HOME_TAX].value
    assert owner.metrics[STABILIZED].value < renter.metrics[STABILIZED].value
