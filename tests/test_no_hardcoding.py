"""Prove nothing is enumerated in code: swap in fake typologies/criteria-free
households and everything still works; and no real typology id appears in code."""

import re
from pathlib import Path

from core.config import ROOT, load_config
from core.engine import analyze


def test_fake_typologies_work(config_copy, lot):
    d, edit = config_copy

    def fake(y):
        y["typologies"] = [
            {"id": "zeta", "label": "Zeta", "color": "#000000", "use_key": "multi_unit",
             "units": {"min": 1, "max": 9}, "lot_sf_per_unit_for_form": 700, "unit_size_sf": 900,
             "stories": 3, "min_lot_sf_for_form": 1000, "tenure_default": "renter"},
            {"id": "omega", "label": "Omega", "color": "#ffffff", "use_key": "two_unit",
             "units": {"min": 2, "max": 2}, "unit_size_sf": 1000, "stories": 2,
             "min_lot_sf_for_form": 1000, "tenure_default": "owner"},
        ]

    def strip_overrides(y):
        for a in y["assumptions"].values():
            a.pop("by_typology", None)

    edit("typologies.yaml", fake)
    edit("assumptions.yaml", strip_overrides)
    cfg = load_config(d)
    a = analyze(cfg, lot)
    assert [s.typology_id for s in a.scenarios] == ["zeta", "omega"]
    assert a.scenarios[0].units == 7  # floor(5000 / 700)


def test_no_typology_ids_in_code():
    cfg = load_config()
    ids = [t.id for t in cfg.typologies] + [p.id for p in cfg.stakeholders.profiles if p.id != "equal"]
    code = [p for d in ("core", "server", "api") for p in (ROOT / d).rglob("*.py")]
    code += [p for p in (ROOT / "web" / "src").rglob("*.ts*")] if (ROOT / "web" / "src").exists() else []
    for path in code:
        text = Path(path).read_text()
        for i in ids:
            assert not re.search(rf"['\"]{re.escape(i)}['\"]", text), f"{i!r} hard-coded in {path}"
