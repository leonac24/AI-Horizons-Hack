import json
import random

import pytest

from core.config import ROOT
from core.engine import analyze

PARCELS = ROOT / "data" / "processed" / "parcels.json"


def _complete(cfg, a):
    assert {s.typology_id for s in a.scenarios} == {t.id for t in cfg.typologies}
    for s in a.scenarios:
        for c in cfg.criteria:
            m = s.metrics[c.metric_id]
            assert m.low <= m.value <= m.high, (s.typology_id, c.metric_id, m)
            assert m.provenance in ("observed", "modeled", "assumption", "placeholder")
        assert len(s.households) == len(cfg.households.households)
        assert len(s.carbon.years) == len(s.carbon.value)


def test_metrics_have_ranges_and_provenance(cfg, lot):
    _complete(cfg, analyze(cfg, lot))


def test_placeholder_inputs_make_placeholder_metrics(cfg, lot):
    a = analyze(cfg, lot)
    # ami_4person is a placeholder in config, so affordability must be too.
    assert cfg.assumption("ami_4person").provenance != "placeholder" or all(
        s.metrics["affordability.ami_needed_pct"].provenance == "placeholder" for s in a.scenarios)


def test_site_hazard_raises_cost(cfg, lot):
    flat = analyze(cfg, {**lot, "steep_slope": False})
    steep = analyze(cfg, {**lot, "steep_slope": True})
    k = "affordability.dev_cost_per_unit"
    assert steep.scenarios[0].metrics[k].value > flat.scenarios[0].metrics[k].value


def test_unknown_hazard_is_not_silently_false(cfg, lot):
    a = analyze(cfg, lot)
    und = next(m for m in a.site_context if m.id == "site.undermined")
    assert und.provenance == "placeholder"


@pytest.mark.skipif(not PARCELS.exists(), reason="run the pipeline first")
def test_coverage_random_citywide_parcels(cfg):
    """Random vacant parcels across the city all return a complete response."""
    parcels = list(json.loads(PARCELS.read_text())["parcels"].values())
    for p in random.Random(42).sample(parcels, 150):
        _complete(cfg, analyze(cfg, p))


def test_work_backwards_honors_unit_count(cfg, lot):
    from core.engine import work_backwards

    t = cfg.typologies[0]
    few = work_backwards(cfg, lot, t.id, 2, 60)
    many = work_backwards(cfg, lot, t.id, 12, 60)
    assert few["units"] == 2 and many["units"] == 12
    # Land cost is spread over more homes, so the per-home gap shrinks.
    assert many["subsidy_per_unit"]["value"] <= few["subsidy_per_unit"]["value"]
