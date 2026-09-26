"""LLM provider interface. Provider and model come from env; `none` disables
LLM calls entirely (callers fall back to deterministic templates)."""

from __future__ import annotations

import json
import os
from typing import Protocol


class LLMUnavailable(RuntimeError):
    pass


class Provider(Protocol):
    name: str

    def complete_json(self, system: str, prompt: str, model: str | None = None) -> dict: ...


class NoProvider:
    name = "none"

    def complete_json(self, system: str, prompt: str, model: str | None = None) -> dict:
        raise LLMUnavailable("LLM_PROVIDER=none")


class GeminiProvider:
    name = "gemini"

    def __init__(self) -> None:
        key = os.environ.get("GEMINI_API_KEY")
        if not key:
            raise LLMUnavailable("GEMINI_API_KEY not set")
        from google import genai  # imported lazily so tests don't need network libs warmed

        self._client = genai.Client(api_key=key)
        self._default_model = os.environ.get("LLM_MODEL", "gemini-3.8-flash")

    def complete_json(self, system: str, prompt: str, model: str | None = None) -> dict:
        from google.genai import types

        try:
            resp = self._client.models.generate_content(
                model=model or self._default_model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=system,
                    response_mime_type="application/json",
                    temperature=0.2,
                ),
            )
            return json.loads(resp.text or "{}")
        except Exception as e:  # network, quota, bad JSON — caller falls back
            raise LLMUnavailable(f"gemini call failed: {e}") from e


def get_provider() -> Provider:
    name = os.environ.get("LLM_PROVIDER", "none").lower()
    try:
        if name == "gemini":
            return GeminiProvider()
    except LLMUnavailable:
        pass
    return NoProvider()
