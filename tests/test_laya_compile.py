from pathlib import Path

import pytest

from pipeline.laya_compile import QUESTIONS, chunks, compile_index, discover, sha256


def _predict(text: str, questions: dict) -> dict:
    assert text and questions == QUESTIONS
    return {"answers": {
        "topic": {"choice": "zoning", "probabilities": {"zoning": 0.8, "other": 0.2}},
    }}


def test_chunks_keep_all_words_and_bound_size():
    text = " ".join(f"word{i}" for i in range(100))
    pieces = chunks(text, max_chars=60)
    assert " ".join(pieces) == text
    assert all(len(piece) <= 60 for piece in pieces)


def test_chunks_rebalance_tiny_tail():
    pieces = chunks(" ".join(["word"] * 21), max_chars=100)
    assert len(pieces) == 2
    assert min(map(len, pieces)) > 40


def test_discover_only_document_inputs(tmp_path: Path):
    (tmp_path / "zoning").mkdir()
    (tmp_path / "laya" / "pgh_zoning_page").mkdir(parents=True)
    (tmp_path / "zoning" / "903.03.txt").write_text("rule", encoding="utf-8")
    (tmp_path / "laya" / "pgh_zoning_page" / "guide.md").write_text("guide", encoding="utf-8")
    (tmp_path / "laya" / "pgh_zoning_page" / "table.json").write_text("{}", encoding="utf-8")
    assert [(sid, path.name) for sid, path in discover(tmp_path)] == [
        ("pgh_zoning_code", "903.03.txt"), ("pgh_zoning_page", "guide.md")]


def test_compiled_index_keeps_source_hash_and_no_legal_verdict(tmp_path: Path):
    source = tmp_path / "903.03.txt"
    source.write_text("The code may require review. " * 4, encoding="utf-8")
    result = compile_index(
        [("pgh_zoning_code", source)], _predict,
        {"pgh_zoning_code": {"url": "https://example.org/code"}},
        "typed-decisions", "0.3.20", root=tmp_path,
    )
    assert result["documents"][0]["sha256"] == sha256(source.read_bytes())
    assert result["passages"][0]["source_url"] == "https://example.org/code"
    assert len(result["passages"][0]["excerpt"].split()) <= 24
    assert result["passages"][0]["topic"] == "zoning"
    assert "reviewed" not in result["passages"][0]
    assert "status" not in result["passages"][0]


def test_unknown_source_rejected(tmp_path: Path):
    source = tmp_path / "a.txt"
    source.write_text("Some text", encoding="utf-8")
    with pytest.raises(ValueError, match="Unknown source id"):
        compile_index([("made_up", source)], _predict, {}, "english", "0.3.20", root=tmp_path)


def test_document_page_url_must_match_registered_host(tmp_path: Path):
    source = tmp_path / "excerpt.txt"
    source.write_text("URL: https://ecode360.com/45474194\nA zoning excerpt", encoding="utf-8")
    registry = {"pgh_zoning_code": {"url": "https://ecode360.com/45474054"}}
    result = compile_index([("pgh_zoning_code", source)], _predict, registry,
                           "typed-decisions", "0.3.20", root=tmp_path)
    assert result["passages"][0]["source_url"] == "https://ecode360.com/45474194"
    source.write_text("URL: https://example.com/wrong\nA zoning excerpt", encoding="utf-8")
    result = compile_index([("pgh_zoning_code", source)], _predict, registry,
                           "typed-decisions", "0.3.20", root=tmp_path)
    assert result["passages"][0]["source_url"] == "https://ecode360.com/45474054"


def test_no_inputs_fails_instead_of_erasing_previous_artifact():
    with pytest.raises(ValueError, match="No source documents"):
        compile_index([], _predict, {}, "english", "0.3.20")
