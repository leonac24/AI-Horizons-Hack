"""Load and validate everything in data/config/. Fails loudly on bad config."""

from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_DIR = ROOT / "data" / "config"

Provenance = Literal["observed", "modeled", "assumption", "placeholder"]


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _Open(BaseModel):
    """Sections whose shape is pipeline-specific; validated where used."""

    model_config = ConfigDict(extra="allow")


# --- app.yaml ------------------------------------------------------------------
class SmaaSettings(_Model):
    samples: int = Field(gt=0)
    seed: int
    profile_concentration: float = Field(gt=0)


class ExplanationSettings(_Model):
    max_sentences: int = Field(gt=0)


class AppConfig(_Model):
    name: str
    tagline: str
    disclaimer: str
    placeholder_notice: str
    smaa: SmaaSettings
    explanation: ExplanationSettings


# --- typologies.yaml -------------------------------------------------------------
class UnitRange(_Model):
    min: int = Field(ge=1)
    max: int = Field(ge=1)

    @model_validator(mode="after")
    def _ordered(self) -> UnitRange:
        if self.max < self.min:
            raise ValueError(f"units.max ({self.max}) < units.min ({self.min})")
        return self


class Typology(_Model):
    id: str
    label: str
    color: str
    use_key: str
    units: UnitRange
    unit_size_sf: float = Field(gt=0)
    stories: float = Field(gt=0)
    min_lot_sf_for_form: float = Field(gt=0)
    lot_sf_per_unit_for_form: float | None = Field(default=None, gt=0)
    tenure_default: Literal["owner", "renter"]
    supports_senior: bool = False


# --- criteria.yaml -------------------------------------------------------------
class Criterion(_Model):
    id: str
    metric_id: str
    label: str
    question: str
    direction: Literal["higher_is_better", "lower_is_better"]
    group: str
    default_weight: float = Field(ge=0)


# --- households.yaml -----------------------------------------------------------
class Household(_Model):
    id: str
    label: str
    description: str
    ami_pct: float = Field(gt=0)
    size: int = Field(ge=1, le=8)
    tenure: Literal["owner", "renter"]
    destination: str


class Destination(_Model):
    label: str
    lon: float | None
    lat: float | None


class HouseholdsConfig(_Model):
    illustrative: Literal[True]
    households: list[Household]
    destinations: dict[str, Destination]

    @model_validator(mode="after")
    def _destinations_exist(self) -> HouseholdsConfig:
        for h in self.households:
            if h.destination not in self.destinations:
                raise ValueError(f"household {h.id!r}: unknown destination {h.destination!r}")
        return self


# --- stakeholders.yaml ---------------------------------------------------------
class StakeholderProfile(_Model):
    id: str
    label: str
    weights: dict[str, float]


class StakeholdersConfig(_Model):
    illustrative: Literal[True]
    profiles: list[StakeholderProfile]


# --- assumptions.yaml ----------------------------------------------------------
class Range(_Model):
    value: float
    low: float
    high: float


class Assumption(_Model):
    value: float
    low: float
    high: float
    unit: str
    provenance: Provenance
    source: str | None
    rationale: str
    by_typology: dict[str, Range] | None = None
    by_size: dict[int, float] | None = None
    by_key: dict[str, float] | None = None

    @model_validator(mode="after")
    def _ordered(self) -> Assumption:
        for label, r in [("", self), *((f"[{k}]", v) for k, v in (self.by_typology or {}).items())]:
            if not (r.low <= r.value <= r.high):
                raise ValueError(f"need low <= value <= high{label}, got {r.low}/{r.value}/{r.high}")
        return self

    def for_typology(self, typology_id: str) -> Range:
        if self.by_typology and typology_id in self.by_typology:
            return self.by_typology[typology_id]
        return Range(value=self.value, low=self.low, high=self.high)


# --- sources.yaml --------------------------------------------------------------
class Source(_Model):
    name: str
    publisher: str
    url: str | None
    access: Literal["ckan_datastore", "ckan_download", "manual"]
    resource_id: str | None = None
    vintage: str
    license: str
    verified: str | bool
    note: str | None = None


class SourcesConfig(_Model):
    ckan_api: str
    sources: dict[str, Source]


# --- zoning.yaml ---------------------------------------------------------------
class ZoningStatus(_Model):
    label: str


class DimensionalTarget(_Model):
    label: str
    unit: str
    check: Literal["lot_area_at_least", "lot_area_per_unit_at_least", "height_at_most", "stories_at_most"]


class ExtractionTargets(_Model):
    use_keys: dict[str, str]
    dimensional: dict[str, DimensionalTarget]
    other: list[str]


class ZoningCode(_Model):
    name: str
    source: str
    url: str
    citation_format: str
    raw_text_dir: str


class ZoningConfig(_Model):
    code: ZoningCode
    rules_file: str
    priority_file: str
    statuses: dict[str, ZoningStatus]
    extraction_targets: ExtractionTargets


# --- everything ----------------------------------------------------------------
class Config(_Model):
    app: AppConfig
    city: _Open
    zoning: ZoningConfig
    typologies: list[Typology]
    criteria: list[Criterion]
    households: HouseholdsConfig
    stakeholders: StakeholdersConfig
    assumptions: dict[str, Assumption]
    sources: SourcesConfig
    hash: str = ""

    @model_validator(mode="after")
    def _cross_refs(self) -> Config:
        errors: list[str] = []
        _unique("typology", [t.id for t in self.typologies], errors)
        _unique("criterion", [c.id for c in self.criteria], errors)
        _unique("household", [h.id for h in self.households.households], errors)
        _unique("stakeholder", [p.id for p in self.stakeholders.profiles], errors)

        crit_ids = {c.id for c in self.criteria}
        for p in self.stakeholders.profiles:
            if set(p.weights) != crit_ids:
                missing, extra = crit_ids - set(p.weights), set(p.weights) - crit_ids
                errors.append(f"stakeholder {p.id!r}: missing {sorted(missing)} extra {sorted(extra)}")
            if any(w < 0 for w in p.weights.values()):
                errors.append(f"stakeholder {p.id!r}: negative weight")

        use_keys = set(self.zoning.extraction_targets.use_keys)
        typ_ids = {t.id for t in self.typologies}
        for t in self.typologies:
            if t.use_key not in use_keys:
                errors.append(f"typology {t.id!r}: use_key {t.use_key!r} not in zoning.yaml use_keys")
        for aid, a in self.assumptions.items():
            if a.source and a.source not in self.sources.sources:
                errors.append(f"assumption {aid!r}: unknown source {a.source!r}")
            for tid in a.by_typology or {}:
                if tid not in typ_ids:
                    errors.append(f"assumption {aid!r}: by_typology has unknown typology {tid!r}")
        if self.zoning.code.source not in self.sources.sources:
            errors.append(f"zoning.code.source {self.zoning.code.source!r} not in sources.yaml")
        if errors:
            raise ValueError("config cross-reference errors:\n  - " + "\n  - ".join(errors))
        return self

    def assumption(self, key: str) -> Assumption:
        try:
            return self.assumptions[key]
        except KeyError:
            raise KeyError(f"assumptions.yaml has no {key!r}") from None

    def public_json(self) -> dict[str, Any]:
        """What the browser gets: everything needed for labels, legends, sliders."""
        return self.model_dump(mode="json")


def _unique(kind: str, ids: list[str], errors: list[str]) -> None:
    seen: set[str] = set()
    for i in ids:
        if i in seen:
            errors.append(f"duplicate {kind} id {i!r}")
        seen.add(i)


_FILES = {
    "app": "app.yaml",
    "city": "city.yaml",
    "zoning": "zoning.yaml",
    "typologies": "typologies.yaml",
    "criteria": "criteria.yaml",
    "households": "households.yaml",
    "stakeholders": "stakeholders.yaml",
    "assumptions": "assumptions.yaml",
    "sources": "sources.yaml",
}


class ConfigError(RuntimeError):
    pass


def load_config(config_dir: Path | str = DEFAULT_CONFIG_DIR) -> Config:
    config_dir = Path(config_dir)
    raw: dict[str, Any] = {}
    for key, fname in _FILES.items():
        path = config_dir / fname
        if not path.exists():
            raise ConfigError(f"missing config file: {path}")
        try:
            data = yaml.safe_load(path.read_text()) or {}
        except yaml.YAMLError as e:
            raise ConfigError(f"{path}: invalid YAML: {e}") from e
        # Some files wrap their list in a same-named key.
        if key in ("typologies", "criteria", "assumptions") and isinstance(data, dict):
            data = data.get(key, data)
        raw[key] = data
    digest = hashlib.sha256(json.dumps(raw, sort_keys=True, default=str).encode()).hexdigest()[:12]
    try:
        cfg = Config(**raw)
    except ValidationError as e:
        raise ConfigError(f"invalid config in {config_dir}:\n{e}") from e
    cfg.hash = digest
    return cfg


@lru_cache(maxsize=1)
def get_config() -> Config:
    return load_config()
