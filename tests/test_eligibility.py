"""A prohibited use is a hard requirement, not a criterion.

The grill decision this pins: "weighted compensation must not make an illegal
scenario appear qualifying." Before this, `not_permitted` merely scored 0.1 on
one of seven criteria, so a low weight on zoning let an illegal scenario rank
first. The engine now marks it ineligible and the server publishes the rankable
set, so the browser cannot score it by accident.
"""

import pytest
import yaml

from core.config import ConfigError, load_config
from core.engine import analyze


def test_prohibited_scenario_is_ineligible_and_excluded(config_copy, lot, monkeypatch, tmp_path):
    d, _edit = config_copy
    base = load_config(d)
    typ = base.typologies[0]
    prohibited = base.zoning.status_id("prohibited")

    rules = tmp_path / "rules_review.yaml"
    rules.write_text(yaml.safe_dump({"districts": {lot["zoning"]: {"uses": {
        typ.use_key: {"status": prohibited, "reviewed": True,
                      "code_section": "911.02", "quote": "not permitted"}}}}}), encoding="utf-8")

    import core.zoning as zoning_mod
    monkeypatch.setattr(zoning_mod, "load_rules", lambda cfg: yaml.safe_load(rules.read_text(encoding="utf-8"))["districts"])
    import core.engine as engine_mod
    monkeypatch.setattr(engine_mod, "load_rules", lambda cfg: yaml.safe_load(rules.read_text(encoding="utf-8"))["districts"])

    a = analyze(load_config(d), lot)
    blocked = next(s for s in a.scenarios if s.typology_id == typ.id)

    assert blocked.zoning.disqualified is True
    assert blocked.eligible is False
    assert blocked.ineligible_reason
    assert typ.id in a.excluded_typology_ids
    assert typ.id not in a.rankable_typology_ids
    # Still returned in full: a CDC needs to see what it cannot do, and why.
    assert blocked.zoning.use_citation
    # And every other typology is still rankable.
    assert len(a.rankable_typology_ids) == len(a.scenarios) - 1


def test_unreviewed_district_is_not_disqualified(cfg, lot):
    """Unknown is not the same as prohibited. An unreviewed district withholds an
    answer; it must never silently exclude a scenario from the ranking."""
    a = analyze(cfg, lot)
    assert a.excluded_typology_ids == []
    assert len(a.rankable_typology_ids) == len(a.scenarios)
    assert all(s.zoning.status == cfg.zoning.status_id("unreviewed") for s in a.scenarios)


def test_config_rejects_a_status_set_missing_a_role(config_copy):
    """Roles are how code avoids naming status ids, so an unresolvable role is a
    startup failure, not a runtime surprise."""
    d, edit = config_copy

    def drop_prohibited(y):
        y["statuses"] = {k: v for k, v in y["statuses"].items() if v.get("role") != "prohibited"}

    edit("zoning.yaml", drop_prohibited)
    with pytest.raises(ConfigError, match="prohibited"):
        load_config(d)


def test_config_rejects_two_statuses_claiming_one_role(config_copy):
    d, edit = config_copy

    def duplicate(y):
        y["statuses"]["also_banned"] = {"label": "Also banned", "role": "prohibited"}

    edit("zoning.yaml", duplicate)
    with pytest.raises(ConfigError):
        load_config(d)
