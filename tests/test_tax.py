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


# --- tension flags ------------------------------------------------------------------
from core.engine import tension_flags
from core.metrics import Metric


def _m(mid, v):
    return Metric(id=mid, label=mid, value=v, low=v, high=v, unit="x", provenance="modeled", sourceIds=[])


def test_tension_flag_fires_only_when_top_and_bottom_coincide(cfg):
    flag = cfg.tension_flags[0]
    crit = {c.id: c for c in cfg.criteria}
    top, bottom = crit[flag.top_on], crit[flag.bottom_on[0]]
    others = [c for c in cfg.criteria if c.id not in (top.id, bottom.id)]

    def option(top_v, bottom_v):
        ms = {top.metric_id: _m(top.metric_id, top_v), bottom.metric_id: _m(bottom.metric_id, bottom_v)}
        for c in others:
            ms[c.metric_id] = _m(c.metric_id, 1.0)
        return ms

    hi_top, lo_top = (10, 1) if top.direction == "higher_is_better" else (1, 10)
    worst_bottom, best_bottom = (10, 1) if bottom.direction == "lower_is_better" else (1, 10)

    got = tension_flags(cfg, {"a": option(hi_top, worst_bottom), "b": option(lo_top, best_bottom)})
    assert [(f.id, f.typology_id, f.bottom_on) for f in got] == [(flag.id, "a", [bottom.id])]
    assert tension_flags(cfg, {"a": option(hi_top, best_bottom), "b": option(lo_top, worst_bottom)}) == []
    assert tension_flags(cfg, {"a": option(hi_top, worst_bottom)}) == []


def test_analysis_carries_tension_flags(cfg, lot):
    a = analyze(cfg, lot)
    assert isinstance(a.tension_flags, list)
    for f in a.tension_flags:
        assert f.typology_id in a.rankable_typology_ids


# --- mixed plans -----------------------------------------------------------------------
def test_plan_sums_revenue_across_building_types(cfg, lot):
    from core.plan import Placement, analyze_plan

    a, b = cfg.typologies[0], cfg.typologies[-1]
    r = analyze_plan(cfg, lot, [Placement(typology_id=a.id, count=1), Placement(typology_id=b.id, count=1)])
    parts = analyze(cfg, lot, homes_override={a.id: a.building.homes, b.id: b.building.homes})
    assert r.metrics[REVENUE].value == pytest.approx(sum(s.metrics[REVENUE].value for s in parts.scenarios), rel=1e-6)
    assert r.revenue.value[-1] == pytest.approx(sum(s.revenue.value[-1] for s in parts.scenarios), abs=2)
    assert len(r.revenue.years) == len(r.carbon.years)


# --- independence guardrail ------------------------------------------------------------
import json
import random

import numpy as np

from core.config import ROOT
from core.scoring import normalize

PARCELS = ROOT / "data" / "processed" / "parcels.json"


def _lots(lot):
    if PARCELS.exists():
        parcels = list(json.loads(PARCELS.read_text(encoding="utf-8"))["parcels"].values())
        return random.Random(7).sample(parcels, 60)
    return [{**lot, "lot_area_sf": a, "land_value_usd": v}
            for a, v in ((3000, 5000), (5000, 10000), (9000, 30000), (20000, 80000))]


def test_public_revenue_is_not_a_restatement_of_another_criterion(cfg, lot):
    """Per lot, not pooled: the `opportunity` failure was a within-lot cancellation,
    and pooling across lots would average it away."""
    max_r = cfg.assumption("criterion_independence_max_corr").value
    new = next(c for c in cfg.criteria if c.metric_id == REVENUE)
    others = [c for c in cfg.criteria if c.id != new.id]
    crits = [new, *others]
    hib = np.array([c.direction == "higher_is_better" for c in crits])
    worst: tuple[float, str, str] = (0.0, "", "")
    checked = 0
    for p in _lots(lot):
        rows = [s for s in analyze(cfg, p).scenarios if s.eligible and s.form_fits]
        if len(rows) < 3:
            continue
        n = normalize(np.array([[s.metrics[c.metric_id].value for c in crits] for s in rows]), hib)
        x = n[:, 0]
        if x.max() == x.min():
            continue
        for j, c in enumerate(others, start=1):
            y = n[:, j]
            if y.max() == y.min():
                continue
            r = abs(float(np.corrcoef(x, y)[0, 1]))
            checked += 1
            if r > worst[0]:
                worst = (r, c.id, str(p.get("id")))
    assert checked > 0
    assert worst[0] < max_r, f"{new.id} vs {worst[1]}: |r|={worst[0]:.4f} on parcel {worst[2]}"


# --- API ---------------------------------------------------------------------------------
def test_unknowns_lists_unreviewed_tax_terms():
    from fastapi.testclient import TestClient

    from server.app import app

    u = TestClient(app).get("/api/unknowns").json()
    assert "unreviewed_tax_terms" in u
    assert all({"id", "label"} <= set(t) for t in u["unreviewed_tax_terms"])
