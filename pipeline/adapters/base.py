"""Shared adapter interface: fetch(config) -> AdapterResult, describe() -> str.

Adapters take locations from config, never read PII fields, return provenance,
and degrade to an empty placeholder result instead of crashing the pipeline.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Protocol

from core.config import Config

log = logging.getLogger("pipeline")


@dataclass
class AdapterResult:
    source_id: str
    data: Any
    provenance: str  # "observed" | "placeholder"
    notes: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.provenance != "placeholder"


class Adapter(Protocol):
    source_id: str

    def fetch(self, config: Config) -> AdapterResult: ...

    def describe(self) -> str: ...


def placeholder(source_id: str, reason: str, empty: Any) -> AdapterResult:
    log.warning("source %s unavailable -> placeholder (%s)", source_id, reason)
    return AdapterResult(source_id, empty, "placeholder", [reason])
