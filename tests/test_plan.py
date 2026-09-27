import pytest
from fastapi.testclient import TestClient

import core.plan as plan_mod
from core.config import get_config
from core.engine import analyze, lot_shape
from core.plan import Placement, analyze_plan
from server.app import app


def _two_types(cfg):
    a, b = cfg.typologies[0], cfg.typologies[-1]
    return a, b


def test_plan_counts_add_and_per_home_measures_average(cfg, lot):
    a, b = _two_types(cfg)
    r = analyze_plan(cfg, lot, [Placement(typology_id=a.id, count=2), Placement(typology_id=b.id, count=1)])
    ha, hb = 2 * a.building.homes, b.building.homes
    assert r.units == ha + hb
    assert r.homes_by_typology == {a.id: ha, b.id: hb}
    alone_a = analyze_plan(cfg, lot, [Placement(typology_id=a.id, count=2)])
    alone_b = analyze_plan(cfg, lot, [Placement(typology_id=b.id, count=1)])
    k = "affordability.ami_needed_pct"
    lo, hi = sorted([alone_a.metrics[k].value, alone_b.metrics[k].value])
    assert lo - 1e-6 <= r.metrics[k].value <= hi + 1e-6
    for m in r.metrics.values():
        assert m.low <= m.value <= m.high


def test_prohibited_building_type_is_flagged_and_plan_is_excluded(cfg, lot, monkeypatch):
    a, b = _two_types(cfg)
    prohibited = cfg.zoning.status_id("prohibited")
    permitted = next(s for s, v in cfg.zoning.statuses.items() if v.role == "permitted")
    base_district, _ = cfg.zoning.district_code.split(lot["zoning"])
    rules = {"districts": {base_district: {"uses": {
        a.use_key: {"status": permitted, "code_section": "1", "quote": "q", "reviewed": True},
        b.use_key: {"status": prohibited, "code_section": "2", "quote": "q", "reviewed": True},
    }}}, "subdistricts": {}, "citywide": {}}
    monkeypatch.setattr(plan_mod, "load_rules", lambda _cfg: rules)
    r = analyze_plan(cfg, lot, [Placement(typology_id=a.id, count=1), Placement(typology_id=b.id, count=1)])
    assert r.failed_typologies == [b.id]
    assert not r.eligible and r.zoning.status == prohibited


def test_empty_or_unknown_plan_rejected(cfg, lot):
    with pytest.raises(ValueError):
        analyze_plan(cfg, lot, [])
    with pytest.raises(KeyError):
        analyze_plan(cfg, lot, [Placement(typology_id="not-a-type", count=1)])


def test_lot_shape_observed_vs_donor_estimate(cfg, lot):
    obs = lot_shape(cfg, {**lot, "frontage_ft": 25, "depth_ft": 200})
    assert (obs.frontage_ft, obs.depth_ft, obs.provenance) == (25, 200, "observed")
    ph = lot_shape(cfg, {**lot, "frontage_ft": None, "depth_ft": None})
    assert ph.provenance == "modeled"
    assert "Not legal frontage" in ph.note
    assert abs(ph.frontage_ft * ph.depth_ft - lot["lot_area_sf"]) < 5
    assert analyze(cfg, lot).lot_shape.provenance == "modeled"


def test_plan_route_limit_comes_from_config():
    client = TestClient(app)
    cap = get_config().app.api.plan_max_buildings
    typ = get_config().typologies[0].id
    pid = "0" * 16
    over = client.post(f"/api/analysis/{pid}/plan", json={"placements": [{"typology_id": typ, "count": cap + 1}]})
    assert over.status_code == 413
