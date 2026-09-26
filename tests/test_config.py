import pytest

from core.config import ConfigError, load_config


def test_real_config_loads(cfg):
    assert cfg.typologies and cfg.criteria and cfg.hash


def test_stakeholders_cover_every_criterion(cfg):
    ids = {c.id for c in cfg.criteria}
    for p in cfg.stakeholders.profiles:
        assert set(p.weights) == ids


def test_duplicate_typology_fails_loudly(config_copy):
    d, edit = config_copy
    edit("typologies.yaml", lambda y: y["typologies"].append(dict(y["typologies"][0])))
    with pytest.raises(ConfigError, match="duplicate typology"):
        load_config(d)


def test_stakeholder_missing_criterion_fails(config_copy):
    d, edit = config_copy
    edit("stakeholders.yaml", lambda y: y["profiles"][0]["weights"].pop(next(iter(y["profiles"][0]["weights"]))))
    with pytest.raises(ConfigError, match="missing"):
        load_config(d)


def test_assumption_range_must_contain_value(config_copy):
    d, edit = config_copy
    edit("assumptions.yaml", lambda y: y["assumptions"]["ami_4person"].update(low=200000))
    with pytest.raises(ConfigError, match="low <= value <= high"):
        load_config(d)


def test_unknown_source_fails(config_copy):
    d, edit = config_copy
    edit("assumptions.yaml", lambda y: y["assumptions"]["ami_4person"].update(source="nope"))
    with pytest.raises(ConfigError, match="unknown source"):
        load_config(d)
