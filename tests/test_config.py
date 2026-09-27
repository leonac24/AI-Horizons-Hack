import pytest

from core.config import ROOT, ConfigError, load_config


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


def test_every_text_file_read_and_write_pins_utf8():
    """Text file IO must name its encoding. No exceptions.

    read_text/write_text default to the platform's preferred encoding: UTF-8 on
    the Linux box this deploys to, cp1252 on a Windows dev machine. So a config
    file holding a section sign or an em dash loads correctly in production and
    silently corrupts locally. The two disagree, and the local one looks like a
    data bug rather than an encoding bug.

    It already cost this repo real time. zoning.yaml's citation_format got
    hand-edited into a genuinely double-encoded state while chasing a mangled
    section sign in the UI, when the bytes were fine and the reader was wrong.

    It matters most in pipeline/zoning/extract.py, which keeps a model's rule
    only if the quote appears verbatim in the Title Nine text. Decode that text
    with the wrong codec and quotes containing a section sign or a curly
    apostrophe stop matching, so correct extractions are silently dropped.

    Uses the AST rather than a regex so prose, comments and this docstring
    cannot trip it.
    """
    import ast

    offenders = []
    for d in ("core", "server", "api", "pipeline", "tests"):
        for path in sorted((ROOT / d).rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr in ("read_text", "write_text")
                    and not any(k.arg == "encoding" for k in node.keywords)
                ):
                    offenders.append(f"{path.relative_to(ROOT)}:{node.lineno}")
    joined = "".join(chr(10) + "  " + o for o in offenders)
    assert not offenders, "text IO without an explicit encoding:" + joined
