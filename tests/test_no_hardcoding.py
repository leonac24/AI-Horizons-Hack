"""Prove nothing is enumerated in code: swap in fake typologies/criteria-free
households and everything still works; and no config-declared id appears in code.

Covers typology ids, stakeholder profile ids, criterion ids and zoning status
ids. Status ids matter as much as the rest: the engine used to branch on the
literal "needs_review" and "not_permitted", which meant renaming a status in
zoning.yaml silently changed behaviour instead of failing loudly.
"""

import re
from pathlib import Path

from core.config import ROOT, load_config
from core.engine import analyze


def _source_files() -> list[Path]:
    files = [p for d in ("core", "server", "api") for p in (ROOT / d).rglob("*.py")]
    if (ROOT / "web" / "src").exists():
        files += list((ROOT / "web" / "src").rglob("*.ts*"))
    return files


def _assert_absent(ids: list[str], files: list[Path], *, allow: dict[str, set[str]] | None = None) -> None:
    allow = allow or {}
    for path in files:
        # Explicit encoding: these files contain non-ASCII (en dashes, CO2e) and
        # the default locale codec is cp1252 on Windows runners.
        text = path.read_text(encoding="utf-8")
        for i in ids:
            if path.name in allow.get(i, set()):
                continue
            assert not re.search(rf"['\"]{re.escape(i)}['\"]", text), f"{i!r} hard-coded in {path}"


def test_fake_typologies_work(config_copy, lot):
    d, edit = config_copy

    def fake(y):
        y["typologies"] = [
            {"id": "zeta", "label": "Zeta", "short_label": "Z", "color": "#000000", "use_key": "multi_unit",
             "unit_size_sf": 900,
             "stories": 3, "min_lot_sf_for_form": 1000, "tenure_default": "renter",
             "building": {"footprint_ft": [20, 50], "homes": 6, "massing": "walkup", "body": "#111111",
                          "roof": "#222222", "max_in_a_row": 3}},
            {"id": "omega", "label": "Omega", "short_label": "O", "color": "#ffffff", "use_key": "two_unit",
             "unit_size_sf": 1000, "stories": 2,
             "min_lot_sf_for_form": 1000, "tenure_default": "owner",
             "building": {"footprint_ft": [20, 40], "homes": 2, "massing": "gable_house", "body": "#333333",
                          "roof": "#444444", "max_in_a_row": 2}},
        ]

    def strip_overrides(y):
        for a in y["assumptions"].values():
            a.pop("by_typology", None)

    edit("typologies.yaml", fake)
    edit("assumptions.yaml", strip_overrides)
    cfg = load_config(d)
    a = analyze(cfg, lot)
    assert [s.typology_id for s in a.scenarios] == ["zeta", "omega"]
    # No legal-description dims on the fixture lot, so the shape is the placeholder
    # ratio; however many 20-ft-wide buildings fit that frontage, capped at 3.
    s = a.scenarios[0]
    assert 1 <= s.buildings <= 3 and s.units == s.buildings * 6


def test_no_typology_or_stakeholder_ids_in_code():
    cfg = load_config()
    ids = [t.id for t in cfg.typologies] + [p.id for p in cfg.stakeholders.profiles if p.id != "equal"]
    _assert_absent(ids, _source_files())


def test_no_criterion_ids_in_code():
    cfg = load_config()
    # Criterion ids drive the weight sliders; the browser must build them from
    # /api/config, never from a list it ships with.
    _assert_absent([c.id for c in cfg.criteria], _source_files())


def test_no_zoning_status_ids_in_code():
    cfg = load_config()
    # config.py names the roles, not the ids, so it is not exempt. The only
    # legitimate mention of a status id anywhere is in zoning.yaml itself.
    _assert_absent(list(cfg.zoning.statuses), _source_files())


def test_no_source_ids_in_code():
    cfg = load_config()
    # Dataset names are Pittsburgh facts, same as zoning codes and housing types.
    # Which public table a number came from should be swappable in config, not
    # baked into the engine.
    #
    # This test was added after finding exactly that: the engine had a dataset
    # name written into a constant at the top of the file, duplicating a name
    # city.yaml was already storing two directories away. The older guard tests
    # checked housing types, criteria, stakeholders and zoning statuses - but
    # nobody had thought to check dataset names, so it slipped through.
    _assert_absent(list(cfg.sources.sources), _source_files())
