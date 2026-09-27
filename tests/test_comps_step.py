"""Comps aggregation is pure: rows in, table out. Network lives in pipeline/build_comps.py."""

from pipeline.steps.comps import aggregate_comps, per_home_values


def _rows(use_class, n, value, hood, year=2015):
    return [{"id": f"{use_class}{i}", "use_class": use_class, "building_value": value,
             "year_built": year, "neighborhood": hood} for i in range(n)]


def test_neighborhood_needs_min_comps_else_citywide_only(cfg):
    typ = cfg.typologies[0]
    uc = typ.assessment_use_classes[0]
    k = cfg.tax.comps.min_comps
    rows = _rows(uc, k, 100000, "Big") + _rows(uc, k - 1, 200000, "Small")
    t = aggregate_comps(cfg, rows)["by_typology"][typ.id]
    assert set(t["neighborhoods"]) == {"Big"}
    assert t["neighborhoods"]["Big"]["n"] == k
    assert t["citywide"]["n"] == 2 * k - 1
    big = t["neighborhoods"]["Big"]
    assert big["low"] <= big["value"] <= big["high"]


def test_old_buildings_and_unknown_classes_are_not_comps(cfg):
    uc = cfg.typologies[0].assessment_use_classes[0]
    rows = _rows(uc, 5, 100000, "X", year=cfg.tax.comps.built_since_year - 1)
    rows.append({"id": "z", "use_class": "NOT A CLASS", "building_value": 1, "year_built": 2020, "neighborhood": "X"})
    rows.append({"id": "nv", "use_class": uc, "building_value": None, "year_built": 2020, "neighborhood": "X"})
    assert dict(per_home_values(cfg, rows)) == {}


def test_unit_band_widens_the_per_home_range(cfg):
    uc, spec = next((u, c) for u, c in cfg.tax.comps.use_classes.items() if c.low is not None and c.high is not None)
    typ = next(t for t in cfg.typologies if uc in t.assessment_use_classes)
    rows = _rows(uc, cfg.tax.comps.min_comps, 1_200_000, "H")
    row = aggregate_comps(cfg, rows)["by_typology"][typ.id]["neighborhoods"]["H"]
    assert row["value"] == round(1_200_000 / spec.homes)
    assert row["low"] == round(1_200_000 / spec.high)
    assert row["high"] == round(1_200_000 / spec.low)


def test_too_few_comps_citywide_gives_no_row(cfg):
    typ = cfg.typologies[0]
    rows = _rows(typ.assessment_use_classes[0], cfg.tax.comps.min_comps - 1, 100000, "X")
    t = aggregate_comps(cfg, rows)["by_typology"][typ.id]
    assert t["citywide"] is None and t["neighborhoods"] == {}
