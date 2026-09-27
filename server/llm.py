"""LLM provider interface. Provider and model come from env; `none` disables
LLM calls entirely (callers fall back to deterministic templates)."""

from __future__ import annotations

import json
import os
from functools import lru_cache
from typing import Literal, Protocol

Effort = Literal["low", "medium", "high", "xhigh", "max"]

DEFAULT_MODEL = "claude-opus-5"
# Opt into server-side refusal fallbacks: a declined request is re-run on
# Anthropic's recommended fallback model inside the same call.
FALLBACK_BETA = "server-side-fallback-2026-07-01"


class LLMUnavailable(RuntimeError):
    pass


class Provider(Protocol):
    name: str

    def complete_json(self, system: str, prompt: str, *, schema: dict | None = None,
                      model: str | None = None, effort: Effort = "high",
                      timeout_s: float | None = None, max_tokens: int = 16000) -> dict: ...


class NoProvider:
    name = "none"

    def __init__(self, reason: str = "LLM_PROVIDER=none") -> None:
        self.reason = reason

    def complete_json(self, system: str, prompt: str, **_: object) -> dict:
        raise LLMUnavailable(self.reason)


class AnthropicProvider:
    name = "anthropic"

    def __init__(self) -> None:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise LLMUnavailable("LLM_PROVIDER=anthropic but ANTHROPIC_API_KEY is not set")
        import anthropic  # imported lazily so the `none` path never loads it

        self._anthropic = anthropic
        self._client = anthropic.Anthropic()
        self._default_model = os.environ.get("LLM_MODEL", DEFAULT_MODEL)

    def complete_json(self, system: str, prompt: str, *, schema: dict | None = None,
                      model: str | None = None, effort: Effort = "high",
                      timeout_s: float | None = None, max_tokens: int = 16000) -> dict:
        """One JSON object back from the model. With `schema`, the API itself
        constrains the output (every object needs additionalProperties: false)."""
        output_config: dict = {"effort": effort}
        if schema is not None:
            output_config["format"] = {"type": "json_schema", "schema": schema}
        client = self._client if timeout_s is None else self._client.with_options(timeout=timeout_s)
        try:
            # Streamed so long inputs (zoning code text) never hit HTTP timeouts.
            with client.beta.messages.stream(
                model=model or self._default_model,
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": prompt}],
                thinking={"type": "adaptive"},
                output_config=output_config,
                betas=[FALLBACK_BETA],
                fallbacks="default",
            ) as stream:
                resp = stream.get_final_message()
        except self._anthropic.APIError as e:  # auth, quota, network, timeout — caller falls back
            raise LLMUnavailable(f"anthropic call failed: {type(e).__name__}: {e}") from e
        if resp.stop_reason != "end_turn":
            raise LLMUnavailable(f"anthropic stopped with {resp.stop_reason}")
        text = next((b.text for b in resp.content if b.type == "text"), "")
        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            raise LLMUnavailable(f"anthropic returned invalid JSON: {e}") from e


@lru_cache(maxsize=1)
def get_provider() -> Provider:
    """Built once per process. A misconfigured provider degrades to NoProvider,
    but keeps the reason so the UI and /health say what is actually wrong."""
    name = os.environ.get("LLM_PROVIDER", "none").lower()
    if name == "none":
        return NoProvider()
    if name != "anthropic":
        return NoProvider(f"unknown LLM_PROVIDER={name!r}")
    try:
        return AnthropicProvider()
    except LLMUnavailable as e:
        return NoProvider(str(e))
