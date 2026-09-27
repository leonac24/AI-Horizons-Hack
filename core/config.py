"""Load and validate everything in data/config/. Fails loudly on bad config."""

from __future__ import annotations

import hashlib
import json
import re
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
    # Draws for the per-criterion leverage runs, and how much change in the
    # leader's first-place share counts as a real effect rather than noise.
    leverage_samples: int = Field(gt=0)
    leverage_epsilon: float = Field(ge=0, le=1)


class UncertaintySettings(_Model):
    """Draw count and seed for the evidence engine's low/high bands."""

    samples: int = Field(gt=0)
    seed: int


class ApiSettings(_Model):
    """The biggest values the API will accept from whoever is calling it.

    Anyone on the internet can call this API. So every number a caller controls
    needs a cap: how long a search box string can be, how many results to hand
    back, how many homes to model. All of those caps are listed right here
    instead of being typed into the route functions further down, which means
    you can see them all at once and change one without editing any Python.

    Three numbers are deliberately NOT in here, because nobody would ever sit
    down and tune them:
      - how many characters of the ETag hash we keep (32),
      - how many IP addresses the rate limiter remembers before it forgets,
      - the "60" in the rate limiter's 60-second window. That 60 is just what
        the word "minute" means in `explain_requests_per_minute`.
    Putting those in config would suggest a reviewer has a decision to make
    about them. They don't.
    """

    search_query_min_chars: int = Field(gt=0)
    search_query_max_chars: int = Field(gt=0)
    search_limit_max: int = Field(gt=0)
    id_param_max_chars: int = Field(gt=0)
    explain_max_weights: int = Field(gt=0)
    explain_max_ranking: int = Field(gt=0)
    explain_requests_per_minute: int = Field(gt=0)
    ask_question_max_chars: int = Field(gt=0)
    lot_search_query_max_chars: int = Field(gt=0)
    lot_search_results_max: int = Field(gt=0)
    analysis_cache_entries: int = Field(gt=0)
    cache_max_age_seconds: int = Field(ge=0)
    work_backwards_max_units: int = Field(gt=0)
    plan_max_buildings: int = Field(gt=0)
    target_ami_pct_max: float = Field(gt=0)

    @model_validator(mode="after")
    def _ordered(self) -> ApiSettings:
        if self.search_query_max_chars < self.search_query_min_chars:
            raise ValueError("api.search_query_max_chars < search_query_min_chars")
        return self


class ExplanationSettings(_Model):
    max_sentences: int = Field(gt=0)
    effort: Literal["low", "medium", "high", "xhigh", "max"]
    timeout_s: float = Field(gt=0)
    max_tokens: int = Field(gt=0)


class AskSettings(_Model):
    search_example: str = ""
    examples: list[str] = Field(default_factory=list)


class EvidenceTopic(_Model):
    label: str
    description: str
    listed: bool = True  # shown as a filter choice in the UI


class EvidenceSettings(_Model):
    question: str
    topics: dict[str, EvidenceTopic] = Field(min_length=1)


class AppConfig(_Model):
    name: str
    tagline: str
    disclaimer: str
    placeholder_notice: str
    uncertainty: UncertaintySettings
    api: ApiSettings
    smaa: SmaaSettings
    explanation: ExplanationSettings
    ask: AskSettings
    evidence: EvidenceSettings


# --- typologies.yaml -------------------------------------------------------------
Massing = Literal["gable_house", "house_with_rear_unit", "gable_house_two_doors", "flat_rowhouse",
                  "walkup", "podium_midrise"]


class Building(_Model):
    """One placeable building of this typology in the 3D lot view."""

    footprint_ft: tuple[float, float]
    homes: int = Field(ge=1)
    massing: Massing
    body: str
    roof: str
    max_in_a_row: int = Field(ge=1)
    # Attached by party walls to homes on neighbouring lots: § 903.03(c) sets the
    # interior side yard to zero on the party-wall side, so side setbacks don't apply.
    party_walls: bool = False

    @model_validator(mode="after")
    def _positive(self) -> Building:
        if min(self.footprint_ft) <= 0:
            raise ValueError("footprint_ft must be positive")
        return self


class Typology(_Model):
    id: str
    label: str
    short_label: str
    color: str
    use_key: str
    unit_size_sf: float = Field(gt=0)
    stories: float = Field(gt=0)
    # Floor-to-floor height. The zoning code caps height in feet, a typology is
    # described in stories; this is the only thing that lets them be compared.
    floor_height_ft: float = Field(gt=0)
    # Screening floor on lot size for this form. Normally left out of
    # typologies.yaml and derived at load time from the building's own footprint
    # and the site_area_per_building_footprint assumption, so the floor is one
    # documented ratio rather than a literal per typology. Set it here only to
    # override a single form deliberately.
    min_lot_sf_for_form: float | None = Field(default=None, gt=0)
    tenure_default: Literal["owner", "renter"]
    supports_senior: bool = False
    building: Building


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


# --- city.yaml ---------------------------------------------------------------
class ParcelIdFormat(_Model):
    """What a parcel id is allowed to look like in this city.

    In Pittsburgh a parcel id is an Allegheny County PIN: capital letters and
    digits only, always within a set length. The API checks an id from a URL
    against this BEFORE it looks anything up. Two things fall out of that:

    1. A junk id gets a "422 Bad Request" straight away and costs us nothing.
    2. An id can never contain a slash or a dot, so nobody can smuggle
       something like "../../secrets.txt" through a URL and reach a real file.

    A different city would number its parcels differently, so this lives in
    city.yaml. Swapping cities is a config edit, not a code edit.
    """

    pattern: str
    min_chars: int = Field(gt=0)
    max_chars: int = Field(gt=0)

    @model_validator(mode="after")
    def _usable(self) -> ParcelIdFormat:
        if self.max_chars < self.min_chars:
            raise ValueError(f"max_chars ({self.max_chars}) < min_chars ({self.min_chars})")
        try:
            re.compile(self.pattern)
        except re.error as e:
            raise ValueError(f"pattern {self.pattern!r} is not a valid regex: {e}") from e
        return self


# --- sources.yaml --------------------------------------------------------------
class Source(_Model):
    name: str
    publisher: str
    url: str | None
    access: Literal["ckan_datastore", "ckan_download", "census_bulk", "arcgis", "manual"]
    resource_id: str | None = None
    vintage: str
    license: str
    verified: str | bool
    note: str | None = None


class SourcesConfig(_Model):
    ckan_api: str
    sources: dict[str, Source]


# --- zoning.yaml ---------------------------------------------------------------
StatusRole = Literal["permitted", "staff_review", "discretionary", "variance", "prohibited", "unreviewed"]

# Roles the engine must be able to resolve to exactly one status id. Code asks
# for a role; zoning.yaml decides which id plays it. No status id in code.
_REQUIRED_ROLES: tuple[StatusRole, ...] = ("variance", "prohibited", "unreviewed")


class ZoningStatus(_Model):
    label: str
    role: StatusRole


class DimensionalTarget(_Model):
    label: str
    unit: str
    check: Literal["lot_area_at_least", "lot_area_per_unit_at_least", "height_at_most", "stories_at_most", "setback"]


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


class DistrictCode(_Model):
    """How a zoning map code splits into the two things the code governs apart.

    Title Nine sets *use* by base district (the Chapter 911 use table is keyed
    R1D, R2, RM ...) and *dimensions* by development subdistrict (§ 903.03 keys
    VL, L, M, H, VH). A map code like `R1D-H` is both at once. Many other codes
    contain a hyphen that is not this split at all — `UC-MU`, `R-MU`, `GT-B`,
    `SP-1` — so a code is only split when the part after its last hyphen is one
    of the suffixes declared here.
    """

    subdistrict_suffixes: list[str]

    def split(self, code: str | None) -> tuple[str | None, str | None]:
        """(base district, subdistrict) — subdistrict is None when the code has none."""
        if not code:
            return None, None
        base, sep, suffix = code.rpartition("-")
        if sep and suffix in self.subdistrict_suffixes:
            return base, suffix
        return code, None


class DistrictColor(_Model):
    prefix: str
    color: str


class ZoningConfig(_Model):
    code: ZoningCode
    rules_file: str
    priority_file: str
    require_human_review: bool
    contextual_setbacks_section: str
    district_code: DistrictCode
    statuses: dict[str, ZoningStatus]
    extraction_targets: ExtractionTargets
    district_colors: list[DistrictColor] = []

    @model_validator(mode="after")
    def _roles_resolvable(self) -> ZoningConfig:
        for role in _REQUIRED_ROLES:
            ids = [i for i, s in self.statuses.items() if s.role == role]
            if len(ids) != 1:
                raise ValueError(
                    f"zoning.statuses needs exactly one status with role {role!r}, found {ids}")
        return self

    def status_id(self, role: StatusRole) -> str:
        """The status id playing `role`. Lets code branch on meaning, not on id."""
        return next(i for i, s in self.statuses.items() if s.role == role)

    def is_disqualifying(self, status_id: str) -> bool:
        """A prohibited use is a hard stop: it is excluded from the ranking rather
        than scored, so no amount of weight on other criteria can outrank it."""
        s = self.statuses.get(status_id)
        return s is not None and s.role == "prohibited"


# --- inquiries.yaml ------------------------------------------------------------
# What to go and find out. Lotline may not say what to build, but it can say what
# is still unknown, who answers it, and what to ask them for — so this file is the
# resolver record for every unknown the evidence layer can surface.
#
# `trigger` is a role, not a name: code asks "which record handles an unreviewed
# use rule?" the same way core/zoning.py asks for the status playing a role. That
# keeps every Pittsburgh-specific string in here rather than in Python.
InquiryTrigger = Literal["public_parcel", "lot_shape", "zoning_use", "zoning_dimensional",
                         "assumption"]

# Triggers that must resolve to exactly one record, because the builder looks them
# up by role rather than by key.
_REQUIRED_TRIGGERS: tuple[InquiryTrigger, ...] = ("public_parcel", "zoning_use")


class CostRange(_Model):
    """An illustrative planning range — what this step tends to cost or take.

    These are estimates about the *user's own predevelopment process*, not claims
    about Pittsburgh or about a parcel, which is why they can live here at all.
    They are always rendered as placeholders, and `core/inquiries.py` keeps them
    out of every ordering so a wrong number here cannot reorder the work plan.
    """

    low: float = Field(ge=0)
    high: float = Field(ge=0)
    unit: str

    @model_validator(mode="after")
    def _ordered(self) -> CostRange:
        if self.high < self.low:
            raise ValueError(f"need low <= high, got {self.low}/{self.high}")
        return self


class Resolver(_Model):
    """Who can answer a question: an agency, a utility, a professional."""

    label: str
    kind: str
    contact_hint: str | None = None


class EffortTier(_Model):
    label: str
    order: int


class InquiryRecord(_Model):
    trigger: InquiryTrigger
    question: str
    why: str
    resolver: str
    ask_for: str
    effort: str
    contact_template: str
    cost: CostRange | None = None
    weeks: CostRange | None = None
    source: str | None = None
    # True when not knowing this can exclude an option outright rather than merely
    # reorder the ranking. No weight can undo an exclusion, so these sort first.
    blocks_eligibility: bool = False
    # The assumption key an answer to this question would settle. It is what lets
    # a question be tied back to the metrics it holds up without any metric id
    # being written in Python: the builder reads the dependency edges the engine
    # recorded and looks this key up among them. For a `trigger: assumption`
    # record the dict key already is that key, so this stays null there.
    pins: str | None = None


class InquiriesConfig(_Model):
    cost_notice: str
    no_leverage_notice: str
    resolvers: dict[str, Resolver]
    effort_tiers: dict[str, EffortTier]
    inquiries: dict[str, InquiryRecord]
    # Used when an assumption has no record of its own, so a new assumption shows
    # up as a real question instead of vanishing. Its text may use {label},
    # {rationale} and {unit}.
    generic: InquiryRecord

    @model_validator(mode="after")
    def _triggers_resolvable(self) -> InquiriesConfig:
        for trigger in _REQUIRED_TRIGGERS:
            ids = [i for i, r in self.inquiries.items() if r.trigger == trigger]
            if len(ids) != 1:
                raise ValueError(
                    f"inquiries needs exactly one record with trigger {trigger!r}, found {ids}")
        return self

    def by_trigger(self, trigger: InquiryTrigger) -> tuple[str, InquiryRecord]:
        """The record playing `trigger`, so code branches on meaning, not on key."""
        return next((i, r) for i, r in self.inquiries.items() if r.trigger == trigger)


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
    inquiries: InquiriesConfig
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

        _unique("criterion metric_id", [c.metric_id for c in self.criteria], errors)

        use_keys = set(self.zoning.extraction_targets.use_keys)
        typ_ids = {t.id for t in self.typologies}
        for t in self.typologies:
            if t.use_key not in use_keys:
                errors.append(f"typology {t.id!r}: use_key {t.use_key!r} not in zoning.yaml use_keys")

        # Every approval path needs a score, or a reviewed district could return a
        # status the engine cannot price.
        zscore = self.assumptions.get("zoning_status_score")
        if zscore is not None:
            missing_scores = set(self.zoning.statuses) - set(zscore.by_key or {})
            if missing_scores:
                errors.append(f"assumptions.zoning_status_score.by_key missing {sorted(missing_scores)}")
        for aid, a in self.assumptions.items():
            if a.source and a.source not in self.sources.sources:
                errors.append(f"assumption {aid!r}: unknown source {a.source!r}")
            for tid in a.by_typology or {}:
                if tid not in typ_ids:
                    errors.append(f"assumption {aid!r}: by_typology has unknown typology {tid!r}")
        if self.zoning.code.source not in self.sources.sources:
            errors.append(f"zoning.code.source {self.zoning.code.source!r} not in sources.yaml")

        # Most of city.yaml is only ever read by the offline pipeline, so we let
        # that file hold whatever keys it wants without checking them. These two
        # are different: the running server uses them on live requests. One
        # checks every parcel id that arrives in a URL, the other records which
        # dataset a number came from.
        #
        # So we check them here, at startup. A typo then crashes the app
        # immediately with a message naming the bad key, instead of causing a
        # confusing 500 error later on whichever request first needed it.
        parcels = self.parcels
        try:
            ParcelIdFormat(pattern=parcels.get("id_pattern"), min_chars=parcels.get("id_min_chars"),
                           max_chars=parcels.get("id_max_chars"))
        except (ValidationError, ValueError) as e:
            errors.append(f"city.parcels id format is unusable: {e}")
        if parcels.get("assessments_source") not in self.sources.sources:
            errors.append(f"city.parcels.assessments_source "
                          f"{parcels.get('assessments_source')!r} not in sources.yaml")

        # inquiries.yaml points at four other files. A dangling pointer here would
        # not crash anything — the work plan would just quietly drop a question —
        # so it has to be caught at startup instead.
        inq = self.inquiries
        dimensional = set(self.zoning.extraction_targets.dimensional)
        for key, rec in [*inq.inquiries.items(), ("generic", inq.generic)]:
            where = f"inquiries.inquiries.{key}"
            if rec.resolver not in inq.resolvers:
                errors.append(f"{where}: unknown resolver {rec.resolver!r}")
            if rec.effort not in inq.effort_tiers:
                errors.append(f"{where}: unknown effort tier {rec.effort!r}")
            if rec.source and rec.source not in self.sources.sources:
                errors.append(f"{where}: unknown source {rec.source!r}")
            if rec.pins and rec.pins not in self.assumptions:
                errors.append(f"{where}: pins unknown assumption {rec.pins!r}")
            if key == "generic":
                continue
            if rec.trigger == "assumption" and key not in self.assumptions:
                errors.append(f"{where}: no assumption named {key!r}")
            if rec.trigger == "zoning_dimensional" and key not in dimensional:
                errors.append(f"{where}: no dimensional rule named {key!r} in zoning.yaml")
        if errors:
            raise ValueError("config cross-reference errors:\n  - " + "\n  - ".join(errors))
        return self

    def assumption(self, key: str) -> Assumption:
        try:
            return self.assumptions[key]
        except KeyError:
            raise KeyError(f"assumptions.yaml has no {key!r}") from None

    def _city(self, key: str) -> dict[str, Any]:
        """Grab one section out of city.yaml, and remember it for next time.

        The `city` config is free-form, so pulling a value out of it means
        converting the whole section into a plain dictionary first. That is
        wasteful to redo for every single parcel, so we do it once and keep the
        result in `cache`.
        """
        cache = self.__dict__.setdefault("_city_sections", {})
        if key not in cache:
            cache[key] = dict(self.city.model_dump().get(key) or {})
        return cache[key]

    @property
    def hazards(self) -> dict[str, Any]:
        """Hazard flag specs from city.yaml, resolved once instead of per parcel."""
        return self._city("hazards")

    @property
    def parcels(self) -> dict[str, Any]:
        """The `parcels` block of city.yaml: id format, dataset names, columns."""
        return self._city("parcels")

    @property
    def parcel_id_format(self) -> ParcelIdFormat:
        """Already checked at startup by `_cross_refs`, so this is safe to call
        inside a request: it will not blow up halfway through serving someone."""
        if self.__dict__.get("_parcel_id_format") is None:
            p = self.parcels
            self.__dict__["_parcel_id_format"] = ParcelIdFormat(
                pattern=p["id_pattern"], min_chars=p["id_min_chars"], max_chars=p["id_max_chars"])
        return self.__dict__["_parcel_id_format"]

    @property
    def assessment_source(self) -> str:
        """Which dataset the real, measured parcel numbers came from.

        "Real, measured" means lot size and assessed land value - things we read
        out of a public file rather than estimated. The engine has to label every
        number with where it came from, but it must NOT know the actual name of
        the Pittsburgh dataset. That name is a Pittsburgh fact, and this code is
        meant to work for any city.

        (The guard test that enforces this is deliberately dumb: it searches for
        dataset names in quotes and cannot tell a docstring from real code. An
        earlier draft of this very paragraph tripped it. Working as intended.)

        So the engine asks a question ("which dataset is the assessment one?")
        and city.yaml answers it. Exactly the same trick the zoning code uses:
        ask for the role, never name the thing directly.
        """
        return str(self.parcels["assessments_source"])

    # Keys stripped from the browser payload: server-side filesystem layout the
    # client has no use for. Not a secret, but publishing your on-disk paths
    # narrows an attacker's guessing and there is no reason to hand it over.
    _INTERNAL_ZONING_KEYS = ("rules_file", "priority_file")
    _INTERNAL_CODE_KEYS = ("raw_text_dir",)

    def public_json(self) -> dict[str, Any]:
        """What the browser gets: everything needed for labels, legends and sliders,
        and nothing about where files live on the server."""
        data = self.model_dump(mode="json")
        zoning = data.get("zoning") or {}
        for k in self._INTERNAL_ZONING_KEYS:
            zoning.pop(k, None)
        for k in self._INTERNAL_CODE_KEYS:
            (zoning.get("code") or {}).pop(k, None)
        return data


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
    "inquiries": "inquiries.yaml",
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
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
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
    # Derive each typology's lot-size screening floor from its own footprint, so
    # the floor tracks the form instead of being a literal someone has to keep in
    # step with it. An explicit value in typologies.yaml wins.
    per_footprint = cfg.assumption("site_area_per_building_footprint").value
    for typ in cfg.typologies:
        if typ.min_lot_sf_for_form is None:
            width, depth = typ.building.footprint_ft
            typ.min_lot_sf_for_form = round(width * depth * per_footprint)
    cfg.hash = digest
    return cfg


@lru_cache(maxsize=1)
def get_config() -> Config:
    return load_config()
