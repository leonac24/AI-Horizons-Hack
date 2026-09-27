from types import SimpleNamespace

import pytest

from server import llm


@pytest.fixture(autouse=True)
def _fresh_provider():
    llm.get_provider.cache_clear()
    yield
    llm.get_provider.cache_clear()


def test_missing_key_reports_real_reason(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    p = llm.get_provider()
    assert p.name == "none"
    with pytest.raises(llm.LLMUnavailable, match="ANTHROPIC_API_KEY"):
        p.complete_json("s", "p")


def test_unknown_provider_named(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    with pytest.raises(llm.LLMUnavailable, match="gemini"):
        llm.get_provider().complete_json("s", "p")


class _Stream:
    def __init__(self, resp, calls, kw):
        self.resp, self.calls, self.kw = resp, calls, kw

    def __enter__(self):
        self.calls.append(self.kw)
        return self

    def __exit__(self, *a):
        return False

    def get_final_message(self):
        return self.resp


def _provider(monkeypatch, resp):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    p = llm.AnthropicProvider()
    calls: list[dict] = []
    stub = SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(
        stream=lambda **kw: _Stream(resp, calls, kw))))
    stub.with_options = lambda **_: stub
    p._client = stub
    return p, calls


def _resp(text, stop="end_turn"):
    return SimpleNamespace(stop_reason=stop, content=[
        SimpleNamespace(type="thinking"), SimpleNamespace(type="text", text=text)])


def test_parses_json_and_sends_schema(monkeypatch):
    p, calls = _provider(monkeypatch, _resp('{"sentences": []}'))
    schema = {"type": "object", "properties": {}, "additionalProperties": False}
    assert p.complete_json("sys", "prompt", schema=schema, effort="low") == {"sentences": []}
    kw = calls[0]
    assert kw["output_config"] == {"effort": "low", "format": {"type": "json_schema", "schema": schema}}
    assert kw["fallbacks"] == "default" and kw["betas"] == [llm.FALLBACK_BETA]


@pytest.mark.parametrize("resp", [_resp("{}", stop="refusal"), _resp("{}", stop="max_tokens"), _resp("not json")])
def test_bad_responses_become_unavailable(monkeypatch, resp):
    p, _ = _provider(monkeypatch, resp)
    with pytest.raises(llm.LLMUnavailable):
        p.complete_json("sys", "prompt")
