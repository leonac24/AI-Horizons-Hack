from core.engine import analyze
from server.explain import build_input, explain, validate
from server.llm import LLMUnavailable


class Fake:
    name = "fake"

    def __init__(self, out):
        self.out = out

    def complete_json(self, system, prompt, **_):
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


class Recorder(Fake):
    def complete_json(self, system, prompt, **kw):
        self.system, self.schema = system, kw.get("schema")
        return super().complete_json(system, prompt, **kw)


def test_request_tells_model_the_grounding_rules(cfg, lot):
    a, ranking, payload = _setup(cfg, lot)
    mid = payload["scenarios"][0]["metrics"][0]["id"]
    p = Recorder({"sentences": [{"text": "Ranks first.", "metric_ids": [mid]}]})
    explain(cfg, p, a, {}, ranking)
    sentences = p.schema["properties"]["sentences"]
    assert sentences["minItems"] == 1
    assert sentences["items"]["properties"]["metric_ids"]["minItems"] == 1
    assert f"at most {cfg.app.explanation.max_sentences} sentences" in p.system
    assert "{max_sentences}" not in p.system


def test_uncited_context_sentence_still_rejected(cfg, lot):
    _a, _ranking, payload = _setup(cfg, lot)
    mid = payload["scenarios"][0]["metrics"][0]["id"]
    out = {"sentences": [{"text": "This lot is vacant.", "metric_ids": []},
                         {"text": "Ranks first.", "metric_ids": [mid]}]}
    assert validate(payload, out, 6) is None


def test_extra_sentences_truncated_not_rejected(cfg, lot):
    _a, _ranking, payload = _setup(cfg, lot)
    mid = payload["scenarios"][0]["metrics"][0]["id"]
    out = {"sentences": [{"text": "Ranks first.", "metric_ids": [mid]}] * 10}
    assert len(validate(payload, out, 6)) == 6
