"""The walk-through and ? buttons point at the UI by id; keep both sides in sync."""

import re

from core.config import ROOT, get_config

WEB = ROOT / "web" / "src"


def _scan(pattern: str) -> set[str]:
    found: set[str] = set()
    for path in WEB.rglob("*.tsx"):
        found.update(re.findall(pattern, path.read_text(encoding="utf-8")))
    return found


def test_every_help_tip_has_text():
    used = _scan(r'<HelpTip id="([^"]+)"')
    assert used, "no HelpTip found; did the component get renamed?"
    missing = used - set(get_config().app.help)
    assert not missing, f"HelpTip ids with no text in app.yaml help: {sorted(missing)}"


def test_every_tour_target_exists_in_the_ui():
    anchors = _scan(r'data-tour="([^"]+)"')
    targets = {s.target for steps in get_config().app.tutorial.chapters.values() for s in steps if s.target}
    missing = targets - anchors
    assert not missing, f"tutorial targets with no data-tour anchor in web/src: {sorted(missing)}"


def test_both_chapters_exist():
    assert set(get_config().app.tutorial.chapters) == {"city", "lot"}
