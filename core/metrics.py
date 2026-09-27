"""Evidence-layer primitives. No weight ever enters anything in this module."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from pydantic import BaseModel

from core.config import Config, Provenance

_RANK: dict[str, int] = {"observed": 0, "modeled": 1, "assumption": 2, "placeholder": 3}


class Metric(BaseModel):
    id: str
    label: str
    value: float
    low: float
    high: float
    unit: str
    provenance: Provenance
    sourceIds: list[str]
    note: str | None = None
    # Which assumptions this number is made of (keys into assumptions.yaml).
    # Recorded by `Trace` as the computation runs, so it cannot drift from the
    # actual arithmetic. core/inquiries.py walks these to work out which real
    # unknowns hold a metric up.
    dependsOn: list[str] = []


def weakest(*provs: str) -> Provenance:
    """A metric is only as strong as its weakest input."""
    return max(provs, key=lambda p: _RANK[p])  # type: ignore[return-value]


@dataclass
class Samples:
    """Vectorized uncertainty: index 0 is the central estimate, 1..n are draws of
    every assumption uniformly within [low, high] (seeded, so ranges are stable).

    Each call to `a()` records which assumptions (and their provenance/sources)
    a computation touched, so every metric reports honest provenance.

    `n` and `seed` default to app.yaml `uncertainty`, so the draw count is a
    reviewable config value rather than a literal buried in the engine. Pass them
    explicitly only in tests.

    `overrides` maps an assumption key to a single number the user says they have
    now gone and found out — a planner's answer, a utility's letter, a quote. An
    overridden assumption stops being a band and becomes a point, which is what
    makes the ranking move when an answer arrives. It does NOT upgrade the
    metric's provenance: the user asserted the value, we did not verify it, and
    the API echoes every override back so the UI can label it as assumed.
    """

    cfg: Config
    n: int = -1
    seed: int = -1
    overrides: dict[str, float] = field(default_factory=dict)
    _cache: dict[tuple, np.ndarray] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.n < 0:
            self.n = self.cfg.app.uncertainty.samples
        if self.seed < 0:
            self.seed = self.cfg.app.uncertainty.seed

    def stream(self, *parts: str) -> np.random.Generator:
        """A generator seeded by this Samples' seed plus `parts`. Anything in the
        engine that needs randomness goes through here, so there is exactly one
        seed in the system and results stay reproducible."""
        return np.random.default_rng([self.seed, *(_stable_hash(p) for p in parts)])

    def a(self, key: str, typology: str | None = None, used: Trace | None = None) -> np.ndarray:
        asm = self.cfg.assumption(key)
        r = asm.for_typology(typology) if typology else asm
        if used is not None:
            used.add(asm.provenance, asm.source, key)
        ck = (key, typology)
        if ck not in self._cache:
            if key in self.overrides:
                # An answer the user has gone and got: one number, no band.
                self._cache[ck] = self.const(self.overrides[key])
            else:
                # Stable per-assumption stream so adding a new assumption doesn't
                # reshuffle the others.
                rng = np.random.default_rng([self.seed, _stable_hash(key), _stable_hash(typology or "")])
                draws = rng.uniform(r.low, r.high, self.n) if r.high > r.low else np.full(self.n, r.value)
                self._cache[ck] = np.concatenate([[r.value], draws])
        return self._cache[ck]

    def const(self, x: float) -> np.ndarray:
        return np.full(self.n + 1, float(x))


@dataclass
class Trace:
    provenance: set[str] = field(default_factory=set)
    sources: set[str] = field(default_factory=set)
    # Assumption keys touched, so a metric can say what it rests on.
    keys: set[str] = field(default_factory=set)

    def add(self, prov: str, source: str | None, key: str | None = None) -> None:
        self.provenance.add(prov)
        if source:
            self.sources.add(source)
        if key:
            self.keys.add(key)

    def merge(self, other: Trace) -> Trace:
        return Trace(self.provenance | other.provenance, self.sources | other.sources,
                     self.keys | other.keys)

    def prov(self) -> Provenance:
        return weakest(*(self.provenance or {"modeled"}))


def to_metric(id: str, label: str, arr: np.ndarray, unit: str, trace: Trace,
              note: str | None = None, provenance: Provenance | None = None) -> Metric:
    central = float(arr[0])
    draws = arr[1:] if arr.size > 1 else arr
    lo, hi = np.percentile(draws, [5, 95]) if draws.size > 1 else (central, central)
    prov = provenance or weakest(trace.prov(), "modeled")
    return Metric(id=id, label=label, value=_r(central), low=_r(min(lo, central)), high=_r(max(hi, central)),
                  unit=unit, provenance=prov, sourceIds=sorted(trace.sources), note=note,
                  dependsOn=sorted(trace.keys))


def _r(x: float) -> float:
    x = float(x)
    if abs(x) >= 100:
        return round(x, 0)
    return round(x, 3)


def _stable_hash(s: str) -> int:
    h = 2166136261
    for ch in s.encode():
        h = ((h ^ ch) * 16777619) & 0xFFFFFFFF
    return h
