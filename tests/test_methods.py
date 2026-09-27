"""Every number with an (i) button has a methods.yaml entry, and every input it
lists is a real assumption with a plain label."""

import re

from core.config import ROOT
from core.engine import analyze

WEB = ROOT / "web" / "src"


def test_every_metric_the_engine_emits_has_a_method(cfg, lot):
    a = analyze(cfg, lot)
    ids = {m.id for m in a.site_context} | {f.id for f in a.site_facts}
    for s in a.scenarios:
        ids |= set(s.metrics)
    missing = ids - set(cfg.methods)
    assert not missing, f"metrics with no methods.yaml entry: {sorted(missing)}"


def test_every_info_tip_id_in_the_ui_has_a_method(cfg):
    used: set[str] = set()
    for path in WEB.rglob("*.tsx"):
        used.update(re.findall(r'<InfoTip\s+id="([^"]+)"', path.read_text(encoding="utf-8")))
    assert used, "no literal InfoTip id found; did the component get renamed?"
    missing = used - set(cfg.methods)
    assert not missing, f"InfoTip ids with no methods.yaml entry: {sorted(missing)}"


def test_metric_inputs_resolve_to_labelled_assumptions(cfg, lot):
    a = analyze(cfg, lot)
    deps = {k for s in a.scenarios for m in s.metrics.values() for k in m.dependsOn}
    assert deps, "metrics report no inputs; the (i) popover would list nothing"
    unknown = deps - set(cfg.assumptions)
    assert not unknown, f"dependsOn keys that are not assumptions: {sorted(unknown)}"
    unlabelled = sorted(k for k, v in cfg.assumptions.items() if not v.label)
    assert not unlabelled, f"assumptions with no label: {unlabelled}"
