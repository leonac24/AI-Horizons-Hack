from core.engine import analyze
from server.explain import build_input, explain, validate
from server.llm import LLMUnavailable


class Fake:
    name = "fake"

    def __init__(self, out):
        self.out = out

    def complete_json(self, system, prompt, model=None):
        if isinstance(self.out, Exception):
            raise self.out
        return self.out


def _setup(cfg, lot):
    a = analyze(cfg, lot)
    ranking = [t.id for t in cfg.typologies]
    return a, ranking, build_input(cfg, a, {}, ranking)


def test_valid_output_accepted(cfg, lot):
    a, ranking, payload = _setup(cfg, lot)
    mid = payload["scenarios"][0]["metrics"][0]["id"]
    out = {"sentences": [{"text": "This option ranks first.", "metric_ids": [mid]}]}
    r = explain(cfg, Fake(out), a, {}, ranking)
    assert r["source"] == "fake"


def test_unknown_metric_id_rejected(cfg, lot):
    a, ranking, payload = _setup(cfg, lot)
    out = {"sentences": [{"text": "Great.", "metric_ids": ["made.up"]}]}
    assert validate(payload, out, 6) is None
    assert explain(cfg, Fake(out), a, {}, ranking)["source"] == "template"


def test_invented_number_rejected(cfg, lot):
    _a, _ranking, payload = _setup(cfg, lot)
    mid = payload["scenarios"][0]["metrics"][0]["id"]
    out = {"sentences": [{"text": "It houses 987654 people.", "metric_ids": [mid]}]}
    assert validate(payload, out, 6) is None


def test_llm_unavailable_falls_back(cfg, lot):
    a, ranking, _ = _setup(cfg, lot)
    r = explain(cfg, Fake(LLMUnavailable("x")), a, {}, ranking)
    assert r["source"] == "template" and r["sentences"]
