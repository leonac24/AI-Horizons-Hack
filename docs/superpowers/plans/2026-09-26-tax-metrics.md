# Tax in the Evidence Layer — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make property tax explicit in Lotline — one new scored criterion (public revenue over the horizon, net of a reviewed abatement), household tax split out of the flat operating-cost placeholder, the parcel's tax status as site context, and a config-driven "high revenue, high exclusion" tension flag.

**Architecture:** A new evidence module `core/tax.py` reads an offline comps table (`data/processed/assessment_comps.json`, built from the county assessment extract) for per-home *assessed* values, multiplies by millage from `assumptions.yaml`, applies any *reviewed* abatement from `tax.yaml`, and returns three metrics plus a cumulative revenue series. `core/engine.py` calls it inside the per-typology loop and computes tension flags after the loop. Every number is an `assumptions.yaml` entry (so it gets ranges, provenance, inquiries and LIMITATIONS counts for free); `tax.yaml` holds only structure and legal terms.

**Tech Stack:** Python 3.14 / uv, pydantic, numpy, pandas (pipeline only), pytest, ruff; Vite + React + TypeScript strict, oxlint.

**Spec:** `docs/superpowers/specs/2026-09-26-tax-metrics-design.md`. Two deliberate deviations, both recorded in Task 10: numbers live in `assumptions.yaml` rather than `tax.yaml` (so the existing `Samples`/`dependsOn`/inquiries machinery applies), and the common level ratio is dropped (comps are already assessed values; the CLR converts market to assessed and never enters).

---

## Baseline (verified 2026-09-26 before any change)

- `uv run pytest -q` → **61 passed, 2 failed**. Both failures pre-exist and are not touched by this plan: `tests/test_eligibility.py::test_prohibited_scenario_is_ineligible_and_excluded` and `tests/test_plan.py::test_prohibited_building_type_is_flagged_and_plan_is_excluded` monkeypatch `load_rules` to return the old flat rules shape, which the uncommitted `districts`/`subdistricts` split in `core/zoning.py` no longer reads. Expect exactly these two to keep failing throughout.
- `uv run ruff check .` → clean.
- The working tree is **dirty with uncommitted work by a teammate** (see Task 0).
- Live WPRDC field names (`TAXDESC`, `FAIRMARKETBUILDING`, `YEARBLT`, `USEDESC`) and the use-class strings in `tax.yaml` were verified against the resource on 2026-09-26. `datastore_search_sql` returns 403; the adapter uses `datastore_search` paging.

## File map

| Action | Path | Responsibility |
|---|---|---|
| Create | `data/config/tax.yaml` | Taxing bodies, homestead rule, abatement programs (with `reviewed`), tax-status vocabulary, comps rules and use-class table |
| Create | `core/tax.py` | Per-home assessed value (comps → citywide → placeholder), scenario tax metrics + revenue series, site tax context |
| Create | `pipeline/steps/comps.py` | Pure aggregation of comp rows into the comps table |
| Create | `pipeline/build_comps.py` | Fetch + neighborhood join + write `assessment_comps.json` |
| Create | `tests/test_tax.py`, `tests/test_comps_step.py` | All new tests |
| Modify | `core/config.py` | `TaxConfig`, `TensionFlag`, `Typology.assessment_use_classes`, loader, cross-refs, `public_json` |
| Modify | `core/engine.py` | Call `core/tax.py`; `Scenario.revenue`; `Analysis.tension_flags`; `tension_flags()` |
| Modify | `core/plan.py` | Sum revenue across building types |
| Modify | `data/config/{assumptions,criteria,stakeholders,typologies,city,sources}.yaml` | New assumptions and sources; new criterion + `tension_flags`; preset weights; use classes; `TAXDESC` keep field |
| Modify | `pipeline/adapters/ckan.py` | Cache key includes fields+filters |
| Modify | `pipeline/build_parcels.py` | Carry `tax_status` into the index |
| Modify | `pipeline/docs.py`, `server/app.py` | Unreviewed tax terms + comps coverage in LIMITATIONS and `/unknowns` |
| Modify | `web/src/{types.ts,lib/plan.ts,components/AnalysisPanel.tsx,components/MemoModal.tsx}` | Types, receipt extras, tension callout, memo line, unknowns section |
| Modify | `docs/{METHODS,LIMITATIONS,AI_DISCLOSURE}.md`, `README.md`, the spec | Documentation |

Commit message convention: `area: what changed`, ending with
`Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.

---

### Task 0: Working-tree hygiene (ask before doing)

**Files:** none edited.

The tree has uncommitted modifications to `core/config.py`, `core/engine.py`, `core/metrics.py`, `core/plan.py`, `core/zoning.py`, several `data/config/*.yaml`, `pipeline/*`, `web/src/*`, plus untracked `core/inquiries.py` and `data/config/inquiries.yaml`. Several of these files are edited by this plan. Committing them mixed into tax commits would misattribute work.

- [ ] **Step 1: Confirm the state**

Run: `git status --short`
Expected: the list above (`M` lines plus two `??`).

- [ ] **Step 2: Do what the user chose** (asked at plan handoff)

Option A (recommended) — commit the pre-existing work as its own commit so tax commits stay clean:
```bash
git add -A
git commit -m "core: inquiries work plan, zoning district/subdistrict split, footprint-derived lot floor (WIP from teammate)"
```
Option B — leave it and let tax commits include it. Then every commit below must `git add` only the files it names, and the first commit that touches a shared file will carry the teammate's hunks.

- [ ] **Step 3: Re-run the baseline**

Run: `uv run pytest -q 2>&1 | tail -3`
Expected: `2 failed, 61 passed` (the two known failures).

---

### Task 1: Config — `tax.yaml`, assumptions, sources, criterion, flags, models

**Files:**
- Create: `data/config/tax.yaml`
- Modify: `data/config/assumptions.yaml`, `data/config/sources.yaml`, `data/config/criteria.yaml`, `data/config/stakeholders.yaml`, `data/config/typologies.yaml`, `data/config/city.yaml`
- Modify: `core/config.py`
- Test: `tests/test_tax.py` (new file, config tests only for now)

- [ ] **Step 1: Write the failing config tests**

Create `tests/test_tax.py`:

```python
"""Tax in the evidence layer. Spec: docs/superpowers/specs/2026-09-26-tax-metrics-design.md."""

import pytest

from core.config import ConfigError, load_config


def test_real_config_loads_tax_and_tension_flags(cfg):
    assert cfg.tax.taxing_bodies and cfg.tax.abatements and cfg.tax.comps.use_classes
    assert cfg.tension_flags, "criteria.yaml should declare at least one tension flag"
    assert any(c.metric_id == "revenue.public_horizon" for c in cfg.criteria)
    assert all(t.assessment_use_classes for t in cfg.typologies)


def test_config_rejects_unknown_assessment_use_class(config_copy):
    d, edit = config_copy
    edit("typologies.yaml", lambda y: y["typologies"][0].__setitem__("assessment_use_classes", ["NOT A CLASS"]))
    with pytest.raises(ConfigError, match="assessment use class"):
        load_config(d)


def test_config_rejects_tension_flag_on_unknown_criterion(config_copy):
    d, edit = config_copy
    edit("criteria.yaml", lambda y: y["tension_flags"][0].__setitem__("top_on", "nope"))
    with pytest.raises(ConfigError, match="tension_flag"):
        load_config(d)


def test_config_rejects_millage_pointing_at_unknown_assumption(config_copy):
    d, edit = config_copy
    edit("tax.yaml", lambda y: y["taxing_bodies"][0].__setitem__("millage", "nope"))
    with pytest.raises(ConfigError, match="unknown assumption"):
        load_config(d)


def test_public_config_hides_the_comps_file_path(cfg):
    assert "file" not in cfg.public_json()["tax"]["comps"]
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_tax.py -q`
Expected: 5 failures (`AttributeError: 'Config' object has no attribute 'tax'` or similar).

- [ ] **Step 3: Create `data/config/tax.yaml`**

```yaml
# Property tax for the City of Pittsburgh: how the numbers fit together and which
# legal terms a person has verified.
#
# Every NUMBER lives in assumptions.yaml and is referenced here by key: millage
# per taxing body, homestead exclusions, abatement years and cap. That way each
# carries value/low/high, a provenance and a source, and shows up automatically
# in the inquiries work plan and the LIMITATIONS placeholder count. "Reviewed"
# for a rate therefore means: its assumption is no longer `provenance:
# placeholder`. Abatement programs carry their own `reviewed` flag because their
# terms are prose (who is eligible, for how long), not a single number.
#
# An unreviewed abatement is NOT applied — the same rule as an unreviewed zoning
# rule — and the horizon revenue metric is a placeholder until it is. We do not
# write tax law from memory.
#
# Assessed values are base-year (Allegheny County: 2012) values, so the tax bill
# is assessed value x millage directly. No common level ratio enters: that ratio
# converts market prices to assessed values, and the comps are already assessed.

taxing_bodies:                 # display order
  - id: city
    label: City of Pittsburgh
    millage: millage_city
    homestead_exclusion: homestead_exclusion_city
  - id: school
    label: Pittsburgh Public Schools
    millage: millage_school
    homestead_exclusion: homestead_exclusion_school
  - id: county
    label: Allegheny County
    millage: millage_county
    homestead_exclusion: homestead_exclusion_county

homestead:
  # Only owner-occupied homes get a homestead exclusion.
  applies_to_tenure: [owner]

abatements:
  # Draft entry. Terms are stand-ins until a teammate reads the ordinance, fills
  # code_section + quote and sets reviewed: true. Until then the program is not
  # applied and horizon revenue is shown as a placeholder.
  - id: residential_new_construction
    label: Residential new-construction tax abatement (City of Pittsburgh)
    eligible_use_keys: [single_unit_detached, single_unit_detached_with_adu, two_unit, single_unit_attached, multi_unit]
    applies_to_bodies: [city, school, county]
    years: abatement_years
    exempt_assessed_cap_usd: abatement_exempt_assessed_cap_usd
    code_section: null
    quote: null
    confidence: null
    reviewed: false
    note: >-
      Pittsburgh offers property tax abatements on new residential construction
      under the City Code, with terms that differ by program and by which taxing
      bodies participate. Verify the current program, its length, its cap and
      its participating bodies before setting reviewed: true.

# The assessment file's tax-status column (mapped to `tax_status` in city.yaml
# keep_fields). Anything not listed here is treated as taxable; a missing value
# is unknown and shown as a placeholder.
status:
  exempt_values: ["10 - Exempt"]

# Observed comparables: what the county assesses EXISTING buildings of each
# housing type at, per home, near this lot. Built by
# `uv run python -m pipeline.build_comps` from the same assessment extract the
# parcel index uses.
comps:
  # Raw assessment columns -> the names pipeline/steps/comps.py works with.
  fields:
    PARID: id
    USEDESC: use_class
    FAIRMARKETBUILDING: building_value
    YEARBLT: year_built
    MUNIDESC: municipality
  # A neighborhood needs this many recent comps of a housing type before its own
  # median is used; otherwise the citywide median is, and the metric says so.
  min_comps: 30
  # We are valuing a NEW building. A 1920 rowhouse's assessment is not evidence
  # for one built today, so only buildings from this year on are comps.
  # Modeling choice: recent enough to be modern construction, old enough that
  # most neighborhoods keep a usable sample.
  built_since_year: 2005
  # The range reported around the median. Must straddle 0.5 so low <= median <= high.
  quantiles: [0.25, 0.75]
  fallback: [neighborhood, citywide]
  file: data/processed/assessment_comps.json
  # USEDESC value -> homes on one parcel of that class. Multi-unit classes are
  # unit BANDS in the county's vocabulary, so `homes` is a midpoint and low/high
  # are the band edges; the pipeline widens the per-home range accordingly. The
  # open-ended 40+ band has no upper edge in the source, so its `high` is a
  # documented cap and the weakest number in this file (see LIMITATIONS.md).
  # Strings verified against the WPRDC resource 2026-09-26 (note the inconsistent
  # spacing after the colon — that is how the county writes them).
  use_classes:
    "SINGLE FAMILY":      { homes: 1 }
    "ROWHOUSE":           { homes: 1 }
    "TOWNHOUSE":          { homes: 1 }
    "TWO FAMILY":         { homes: 2 }
    "APART: 5-19 UNITS":  { homes: 12, low: 5, high: 19 }
    "APART:20-39 UNITS":  { homes: 29, low: 20, high: 39 }
    "APART:40+ UNITS":    { homes: 60, low: 40, high: 120 }
```

- [ ] **Step 4: Add the tax assumptions to `data/config/assumptions.yaml`**

Replace the existing `operating_cost_per_unit_month` block with:

```yaml
  operating_cost_per_unit_month:
    value: 300
    low: 220
    high: 420
    unit: USD/unit/month
    provenance: placeholder
    source: null
    rationale: >-
      Insurance, maintenance, management, reserves. Property tax is NOT in here:
      it is computed per home from assessed value and millage in core/tax.py and
      added to the monthly cost separately (tax.per_home_monthly).
```

Append this block before `# --- Scoring conventions`:

```yaml
  # --- Property tax --------------------------------------------------------------
  # Structure (which body, which homes, which program) is in tax.yaml; the
  # numbers are here so they carry ranges and provenance like everything else.
  # Every value marked STAND-IN is a placeholder until a teammate verifies it
  # against the published rate or ordinance and flips provenance to observed.
  millage_city:
    value: 8
    low: 4
    high: 12
    unit: mills
    provenance: placeholder
    source: pgh_city_millage
    rationale: >-
      STAND-IN, not the published rate. City of Pittsburgh real estate tax rate in
      mills (tax per $1,000 of assessed value). Fill from the City's current
      budget ordinance.

  millage_school:
    value: 10
    low: 5
    high: 15
    unit: mills
    provenance: placeholder
    source: pps_millage
    rationale: STAND-IN. Pittsburgh Public Schools real estate tax rate in mills; fill from the District's adopted budget.

  millage_county:
    value: 5
    low: 3
    high: 8
    unit: mills
    provenance: placeholder
    source: allegheny_millage
    rationale: STAND-IN. Allegheny County real estate tax rate in mills; fill from the County's adopted budget.

  homestead_exclusion_city:
    value: 10000
    low: 0
    high: 30000
    unit: USD assessed value
    provenance: placeholder
    source: pgh_city_millage
    rationale: STAND-IN. Assessed value excluded from City tax for an owner-occupied home (homestead exclusion). Fill from the City.

  homestead_exclusion_school:
    value: 10000
    low: 0
    high: 30000
    unit: USD assessed value
    provenance: placeholder
    source: pps_millage
    rationale: STAND-IN. Assessed value excluded from School District tax for an owner-occupied home. Fill from the District.

  homestead_exclusion_county:
    value: 10000
    low: 0
    high: 30000
    unit: USD assessed value
    provenance: placeholder
    source: allegheny_millage
    rationale: STAND-IN. Assessed value excluded from County tax for an owner-occupied home. Fill from the County Treasurer.

  abatement_years:
    value: 10
    low: 0
    high: 15
    unit: years
    provenance: placeholder
    source: pgh_tax_abatement
    rationale: >-
      STAND-IN. Length of the residential new-construction abatement declared in
      tax.yaml. Fill from the ordinance; applied only once that program is
      reviewed there.

  abatement_exempt_assessed_cap_usd:
    value: 150000
    low: 0
    high: 300000
    unit: USD assessed value per home per year
    provenance: placeholder
    source: pgh_tax_abatement
    rationale: STAND-IN. Most building (improvement) assessed value the abatement exempts per home each year. Fill from the ordinance.

  assessed_building_value_per_home:
    value: 60000
    low: 20000
    high: 150000
    unit: USD assessed value
    provenance: placeholder
    source: null
    rationale: >-
      Used ONLY when no assessment comps exist for a housing type (comps file not
      built yet). Base-year assessed value of one new home's building. Run
      `uv run python -m pipeline.build_comps` to replace it with observed medians.
    by_typology:
      detached:    { value: 90000, low: 40000, high: 180000 }
      adu_pair:    { value: 60000, low: 25000, high: 120000 }
      two_unit:    { value: 55000, low: 20000, high: 110000 }
      rowhouse:    { value: 70000, low: 25000, high: 150000 }
      small_multi: { value: 35000, low: 12000, high: 80000 }
      midrise:     { value: 45000, low: 15000, high: 100000 }

  criterion_independence_max_corr:
    value: 0.999
    low: 0.999
    high: 0.999
    unit: "|r|"
    provenance: assumption
    source: null
    rationale: >-
      Guardrail used by tests/test_tax.py, not by the engine. On one lot, a
      criterion that is an affine function of another has |r| = 1 to machine
      precision and cancels against it in the weighted sum (the `opportunity`
      failure of 2026-09-26). Two criteria that merely share home count as a
      driver land near 0.99 on lots where one option is far denser than the rest;
      that is a fact about the lot, not a defect. So the guard sits just under 1:
      it catches identities, not tendencies.
```

- [ ] **Step 5: Add the sources to `data/config/sources.yaml`** (append under `sources:`)

```yaml
  pgh_city_millage:
    name: City of Pittsburgh real estate tax rate and homestead exclusion
    publisher: City of Pittsburgh, Department of Finance
    url: null
    access: manual
    vintage: not yet retrieved
    license: public record
    verified: false
    note: Set annually in the City budget ordinance. Fill assumptions.yaml millage_city and homestead_exclusion_city for the current year, record the URL and retrieval date here.

  pps_millage:
    name: Pittsburgh Public Schools real estate tax rate and homestead exclusion
    publisher: School District of Pittsburgh
    url: null
    access: manual
    vintage: not yet retrieved
    license: public record
    verified: false
    note: Fill assumptions.yaml millage_school and homestead_exclusion_school from the District's adopted budget.

  allegheny_millage:
    name: Allegheny County real estate tax rate and homestead exclusion
    publisher: Allegheny County Treasurer
    url: null
    access: manual
    vintage: not yet retrieved
    license: public record
    verified: false
    note: Fill assumptions.yaml millage_county and homestead_exclusion_county from the County's adopted budget.

  pgh_tax_abatement:
    name: City of Pittsburgh residential tax abatement programs (Pittsburgh Code of Ordinances)
    publisher: City of Pittsburgh (hosted by General Code / eCode360)
    url: null
    access: manual
    vintage: not yet retrieved
    license: public law
    verified: false
    note: eCode360 blocks scripted requests. Read the abatement chapters in a browser, fill tax.yaml abatements (code_section, quote) and the abatement_* assumptions, then set reviewed true.
```

- [ ] **Step 6: Add the criterion and tension flag to `data/config/criteria.yaml`**

Append inside the `criteria:` list, after the `carbon` entry:

```yaml
  # Added 2026-09-26 (spec: docs/superpowers/specs/2026-09-26-tax-metrics-design.md).
  # Total property tax the parcel yields over the analysis horizon, net of any
  # reviewed abatement. It passes both tests at the top of this file: it varies by
  # housing type (homes x per-home assessed value, and the county comps give each
  # type its own value), and that value comes from observed comps rather than from
  # development cost, so it is not a restatement of `affordability`.
  # tests/test_tax.py enforces the second point on real lots.
  - id: public_revenue
    metric_id: revenue.public_horizon
    label: Public revenue
    question: How much property tax would this option return to the City, the school district and the county over the analysis horizon?
    direction: higher_is_better
    group: fiscal
    default_weight: 1
```

Append at the end of the file (top level, beside `criteria:`):

```yaml
# Patterns worth naming out loud. The option best on `top_on` that is also worst
# on any of `bottom_on` gets this message in the tradeoff receipt and the memo.
# A rank on one criterion involves no weights, so this is evidence, computed by
# the engine, not a judgment about what should be built.
tension_flags:
  - id: revenue_vs_affordability
    label: High revenue, high exclusion
    top_on: public_revenue
    bottom_on: [affordability, local_affordability_gap]
    message: >-
      This option yields the most public revenue and is also the least affordable
      of the options compared. Both are true at once; which matters more is a
      values question, not an evidence one.
```

- [ ] **Step 7: Add `public_revenue` to every profile in `data/config/stakeholders.yaml`**

Edit each `weights:` map to add the key (values are illustrative starting points, like the rest of the file):

| profile | public_revenue |
|---|---|
| equal | 1 |
| resident | 0.25 |
| cdc | 0.5 |
| developer | 0.5 |
| city_planning | 2 |
| ura | 2 |
| climate | 0.25 |

Also add this comment above `profiles:`:
```yaml
# `public_revenue` is what the City, the School District and the County collect;
# a developer weighs their own tax bill, which is the occupant/opex side, so the
# developer preset keeps this low. City Planning and the URA weigh it high.
```

- [ ] **Step 8: Add `assessment_use_classes` to each typology in `data/config/typologies.yaml`**

Add to the header comment:
```yaml
# `assessment_use_classes` are the county assessment USEDESC values whose
# existing buildings stand in for this form when estimating what a new one would
# be assessed at (tax.yaml comps.use_classes has the full table). A proxy is a
# proxy: house + ADU uses TWO FAMILY because that is the closest class holding
# two homes on one lot.
```
Then, per typology, insert after `use_key:`:

| typology | line |
|---|---|
| detached | `assessment_use_classes: ["SINGLE FAMILY"]` |
| adu_pair | `assessment_use_classes: ["TWO FAMILY"]` |
| two_unit | `assessment_use_classes: ["TWO FAMILY"]` |
| rowhouse | `assessment_use_classes: ["ROWHOUSE", "TOWNHOUSE"]` |
| small_multi | `assessment_use_classes: ["APART: 5-19 UNITS"]` |
| midrise | `assessment_use_classes: ["APART:20-39 UNITS", "APART:40+ UNITS"]` |

- [ ] **Step 9: Carry tax status through `data/config/city.yaml`**

In `parcels.keep_fields` add `TAXDESC: tax_status` after `OWNERDESC: owner_type`.

- [ ] **Step 10: Add the models to `core/config.py`**

In `class Typology`, after `use_key: str`:
```python
    # County assessment use classes whose existing buildings stand in for this
    # form's assessed value (keys into tax.yaml comps.use_classes). Empty means
    # the placeholder assumption is used.
    assessment_use_classes: list[str] = []
```

After the `Criterion` class:
```python
class TensionFlag(_Model):
    """A pattern worth naming: the option best on `top_on` is also worst on any of
    `bottom_on`. A rank on one criterion involves no weights, so this is evidence."""

    id: str
    label: str
    top_on: str
    bottom_on: list[str]
    message: str
```

Before `# --- inquiries.yaml`, add the tax section:
```python
# --- tax.yaml ------------------------------------------------------------------
# Property tax structure. Every NUMBER (a millage rate, an exclusion, an abatement
# term) is an assumptions.yaml entry referenced here by key, so it carries a
# range, a provenance and a source and shows up in inquiries and LIMITATIONS like
# any other number the engine uses. This file says how those numbers combine and
# which legal terms a person has verified.
class TaxingBody(_Model):
    id: str
    label: str
    millage: str  # assumptions.yaml key, in mills
    homestead_exclusion: str | None = None  # assumptions.yaml key, USD of assessed value


class HomesteadRule(_Model):
    applies_to_tenure: list[Literal["owner", "renter"]]


class AbatementProgram(_Model):
    id: str
    label: str
    eligible_use_keys: list[str]
    applies_to_bodies: list[str]
    years: str  # assumptions.yaml key
    exempt_assessed_cap_usd: str  # assumptions.yaml key
    code_section: str | None = None
    quote: str | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    reviewed: bool = False
    note: str | None = None


class TaxStatusRule(_Model):
    # Values of the assessment file's tax-status column that mean "pays no tax".
    exempt_values: list[str]


class CompClass(_Model):
    """One assessment use class and how many homes a parcel of it holds. Multi-unit
    classes are unit bands, so `homes` is a midpoint with the band edges as range."""

    homes: float = Field(gt=0)
    low: float | None = Field(default=None, gt=0)
    high: float | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def _ordered(self) -> CompClass:
        lo, hi = self.band()
        if not (lo <= self.homes <= hi):
            raise ValueError(f"need low <= homes <= high, got {lo}/{self.homes}/{hi}")
        return self

    def band(self) -> tuple[float, float]:
        return (self.low if self.low is not None else self.homes,
                self.high if self.high is not None else self.homes)


class CompsRule(_Model):
    fields: dict[str, str]  # raw assessment column -> canonical name
    min_comps: int = Field(gt=0)
    built_since_year: int
    quantiles: tuple[float, float]
    fallback: list[Literal["neighborhood", "citywide"]]
    file: str
    use_classes: dict[str, CompClass]

    @model_validator(mode="after")
    def _shape(self) -> CompsRule:
        need = {"id", "use_class", "building_value", "year_built", "municipality"}
        got = set(self.fields.values())
        if got != need:
            raise ValueError(f"comps.fields must map onto exactly {sorted(need)}, got {sorted(got)}")
        lo, hi = self.quantiles
        if not (0 <= lo <= 0.5 <= hi <= 1):
            raise ValueError("comps.quantiles must satisfy 0 <= low <= 0.5 <= high <= 1")
        if not self.fallback:
            raise ValueError("comps.fallback needs at least one level")
        return self


class TaxConfig(_Model):
    taxing_bodies: list[TaxingBody]
    homestead: HomesteadRule
    abatements: list[AbatementProgram]
    status: TaxStatusRule
    comps: CompsRule

    @model_validator(mode="after")
    def _bodies(self) -> TaxConfig:
        ids = [b.id for b in self.taxing_bodies]
        if not ids or len(set(ids)) != len(ids):
            raise ValueError(f"taxing_bodies ids must be unique and non-empty, got {ids}")
        for a in self.abatements:
            bad = set(a.applies_to_bodies) - set(ids)
            if bad:
                raise ValueError(f"abatement {a.id!r}: unknown taxing bodies {sorted(bad)}")
        return self
```

In `class Config`, add two fields after `inquiries: InquiriesConfig`:
```python
    tax: TaxConfig
    tension_flags: list[TensionFlag] = []
```

In `_cross_refs`, directly after the loop `for t in self.typologies: if t.use_key not in use_keys: ...`, add:
```python
        # tax.yaml points at assumptions, zoning use keys and assessment use
        # classes; criteria.yaml tension_flags point at criteria.
        for b in self.tax.taxing_bodies:
            for key in (b.millage, b.homestead_exclusion):
                if key and key not in self.assumptions:
                    errors.append(f"tax.taxing_bodies[{b.id}]: unknown assumption {key!r}")
        for a in self.tax.abatements:
            for key in (a.years, a.exempt_assessed_cap_usd):
                if key not in self.assumptions:
                    errors.append(f"tax.abatements[{a.id}]: unknown assumption {key!r}")
            for uk in a.eligible_use_keys:
                if uk not in use_keys:
                    errors.append(f"tax.abatements[{a.id}]: use_key {uk!r} not in zoning.yaml use_keys")
        for t in self.typologies:
            for uc in t.assessment_use_classes:
                if uc not in self.tax.comps.use_classes:
                    errors.append(f"typology {t.id!r}: assessment use class {uc!r} not in tax.yaml comps.use_classes")
        _unique("tension_flag", [f.id for f in self.tension_flags], errors)
        for f in self.tension_flags:
            for cid in (f.top_on, *f.bottom_on):
                if cid not in crit_ids:
                    errors.append(f"tension_flag {f.id!r}: unknown criterion {cid!r}")
            if f.top_on in f.bottom_on:
                errors.append(f"tension_flag {f.id!r}: top_on also appears in bottom_on")
```

In `public_json`, add a class attribute next to `_INTERNAL_CODE_KEYS`:
```python
    _INTERNAL_TAX_COMPS_KEYS = ("file",)
```
and inside `public_json`, before `return data`:
```python
        comps = (data.get("tax") or {}).get("comps") or {}
        for k in self._INTERNAL_TAX_COMPS_KEYS:
            comps.pop(k, None)
```

In `_FILES`, add `"tax": "tax.yaml",` after `"inquiries"`.

In `load_config`, replace the wrapping block:
```python
        # Some files wrap their list in a same-named key.
        if key in ("typologies", "criteria", "assumptions") and isinstance(data, dict):
            data = data.get(key, data)
        raw[key] = data
```
with:
```python
        # Some files wrap their list in a same-named key. criteria.yaml also
        # carries `tension_flags` beside its list.
        if key == "criteria" and isinstance(data, dict):
            raw["tension_flags"] = data.get("tension_flags") or []
            data = data.get("criteria", data)
        elif key in ("typologies", "assumptions") and isinstance(data, dict):
            data = data.get(key, data)
        raw[key] = data
    raw.setdefault("tension_flags", [])
```
(The `raw.setdefault` line goes after the `for` loop, before `digest = ...`.)

- [ ] **Step 11: Run the config tests and the whole suite**

Run: `uv run pytest tests/test_tax.py tests/test_config.py tests/test_no_hardcoding.py -q`
Expected: all pass.

Run: `uv run pytest -q 2>&1 | tail -3`
Expected: only the 2 known failures.

- [ ] **Step 12: Lint and commit**

```bash
uv run ruff check .
git add data/config/tax.yaml data/config/assumptions.yaml data/config/sources.yaml data/config/criteria.yaml data/config/stakeholders.yaml data/config/typologies.yaml data/config/city.yaml core/config.py tests/test_tax.py
git commit -m "config: property tax structure, millage and abatement placeholders, public_revenue criterion, tension flags

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 2: `core/tax.py` — per-home assessed value with fallback

**Files:**
- Create: `core/tax.py`
- Test: `tests/test_tax.py`

- [ ] **Step 1: Write the failing test** (append to `tests/test_tax.py`)

```python
from core.metrics import Samples
from core.tax import per_home_assessed


def _comps(cfg, value=50000, low=40000, high=60000, hoods=("Test",)):
    """A comps table with the same row for every typology."""
    row = {"value": value, "low": low, "high": high, "n": 99}
    return {"by_typology": {t.id: {"citywide": dict(row), "neighborhoods": {h: dict(row) for h in hoods}}
                            for t in cfg.typologies}}


def test_comps_fallback_order_neighborhood_citywide_placeholder(cfg):
    S = Samples(cfg)
    typ = cfg.typologies[0]
    table = _comps(cfg, 70000, 60000, 80000, hoods=("Here",))
    hood = per_home_assessed(cfg, S, typ, "Here", table)
    assert hood.provenance == "observed" and hood.note is None and hood.draws[0] == 70000
    assert 60000 <= hood.draws[1:].min() and hood.draws[1:].max() <= 80000
    city = per_home_assessed(cfg, S, typ, "Elsewhere", table)
    assert city.provenance == "observed" and "citywide" in (city.note or "")
    none = per_home_assessed(cfg, S, typ, "Here", {})
    assert none.provenance == "placeholder"
    assert none.draws[0] == cfg.assumption("assessed_building_value_per_home").for_typology(typ.id).value
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_tax.py -q -k fallback`
Expected: `ModuleNotFoundError: No module named 'core.tax'`.

- [ ] **Step 3: Create `core/tax.py`**

```python
"""Property tax in the evidence layer: what a scenario's homes would pay, what the
public would collect over the horizon, and what the lot pays today. No weight
enters anything here.

Assessed values come from observed county comparables (built by
pipeline/build_comps.py), never from development cost: Allegheny County
assessments are base-year values, so a cost-derived figure would be wrong by
roughly 2x and would duplicate the cost criterion besides.

Every number is an assumptions.yaml entry named in tax.yaml; nothing about the
city's tax structure is written here. Formulas: docs/METHODS.md.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import numpy as np
from pydantic import BaseModel

from core.config import ROOT, Config, Typology
from core.metrics import Metric, Samples, Trace, to_metric, weakest


class RevenueSeries(BaseModel):
    """Cumulative property tax the parcel yields, year 0..horizon, net of any
    reviewed abatement. Same shape as the carbon series so the UI can share a chart."""

    years: list[int]
    value: list[float]
    low: list[float]
    high: list[float]
    provenance: str
    abated_years: int = 0


@lru_cache(maxsize=4)
def _load_comps(path: str, mtime: float) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8")) or {}


def load_comps(cfg: Config) -> dict:
    """The comps table, or {} when the pipeline has not built it (placeholder path)."""
    p = ROOT / cfg.tax.comps.file
    if not p.exists():
        return {}
    return _load_comps(str(p), p.stat().st_mtime)


@dataclass
class AssessedHome:
    """Per-home assessed BUILDING value draws, and where they came from."""

    draws: np.ndarray
    trace: Trace
    provenance: str  # observed | placeholder
    note: str | None = None


def per_home_assessed(cfg: Config, S: Samples, typ: Typology, neighborhood: str | None,
                      comps: dict) -> AssessedHome:
    """Neighborhood comps, else citywide comps, else the placeholder assumption —
    in the order tax.yaml `comps.fallback` declares."""
    table = (comps.get("by_typology") or {}).get(typ.id) or {}
    for level in cfg.tax.comps.fallback:
        row = None
        if level == "neighborhood" and neighborhood:
            row = (table.get("neighborhoods") or {}).get(neighborhood)
        elif level == "citywide":
            row = table.get("citywide")
        if not row:
            continue
        value, lo, hi = float(row["value"]), float(row["low"]), float(row["high"])
        rng = S.stream("assessment_comps", typ.id, level, neighborhood or "")
        draws = rng.uniform(lo, hi, S.n) if hi > lo else np.full(S.n, value)
        note = None if level == "neighborhood" else (
            f"Too few recent comps in this neighborhood; citywide median of {row['n']} buildings used.")
        return AssessedHome(np.concatenate([[value], draws]), Trace({"observed"}, {cfg.assessment_source}),
                            "observed", note)
    t = Trace()
    draws = S.a("assessed_building_value_per_home", typ.id, t)
    return AssessedHome(draws, t, "placeholder", "No assessment comps built yet; placeholder per-home value.")
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/test_tax.py -q -k fallback`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
uv run ruff check core/tax.py tests/test_tax.py
git add core/tax.py tests/test_tax.py
git commit -m "core: per-home assessed value from county comps with citywide and placeholder fallback

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 3: Scenario tax metrics, revenue series, site context, engine integration

**Files:**
- Modify: `core/tax.py`, `core/engine.py`
- Test: `tests/test_tax.py`, `tests/test_no_hardcoding.py`

- [ ] **Step 1: Write the failing tests** (append to `tests/test_tax.py`)

```python
import core.engine as engine_mod
from core.engine import analyze
from core.tax import scenario_tax

REVENUE = "revenue.public_horizon"
STABILIZED = "revenue.annual_stabilized"
HOME_TAX = "tax.per_home_monthly"


def _pin(y, key, value):
    y["assumptions"][key].update(value=value, low=value, high=value)


def test_every_scenario_has_tax_metrics_and_a_revenue_series(cfg, lot):
    a = analyze(cfg, lot)
    for s in a.scenarios:
        for mid in (REVENUE, STABILIZED, HOME_TAX):
            m = s.metrics[mid]
            assert m.low <= m.value <= m.high and m.value >= 0, (s.typology_id, mid)
        assert len(s.revenue.years) == len(s.carbon.years)
        assert s.revenue.value[0] == 0
        assert s.revenue.value[-1] == pytest.approx(s.metrics[REVENUE].value, abs=1)
    assert {"site.tax_status_today", "site.tax_today"} <= {m.id for m in a.site_context}


def test_unreviewed_abatement_is_not_applied_and_marks_revenue_placeholder(cfg, lot):
    assert any(not a.reviewed for a in cfg.tax.abatements), "assumes the shipped program is unreviewed"
    a = analyze(cfg, lot)
    years = int(cfg.assumption("analysis_years").value)
    for s in a.scenarios:
        assert s.metrics[REVENUE].provenance == "placeholder"
        assert s.revenue.abated_years == 0
        assert s.metrics[REVENUE].value == pytest.approx(years * s.metrics[STABILIZED].value, rel=1e-3)


def _review_and_pin(edit, years_value, homestead=0):
    def review(y):
        for p in y["abatements"]:
            p.update(reviewed=True, code_section="999.99", quote="test quote")
    edit("tax.yaml", review)

    def pin(y):
        _pin(y, "abatement_years", years_value)
        _pin(y, "abatement_exempt_assessed_cap_usd", 1e9)  # cap never binds
        for key in list(y["assumptions"]):
            if key.startswith("millage_"):
                _pin(y, key, y["assumptions"][key]["value"])
            if key.startswith("homestead_exclusion_"):
                _pin(y, key, homestead)
    edit("assumptions.yaml", pin)


def test_reviewed_abatement_removes_exactly_the_abated_amount(config_copy, lot, monkeypatch):
    d, edit = config_copy
    _review_and_pin(edit, years_value=10)
    cfg = load_config(d)
    monkeypatch.setattr(engine_mod, "load_comps", lambda _cfg: _comps(cfg, 50000, 50000, 50000))
    a = analyze(cfg, lot)
    mills = sum(cfg.assumption(b.millage).value for b in cfg.tax.taxing_bodies)
    years = int(cfg.assumption("analysis_years").value)
    for s in a.scenarios:
        gross = years * s.metrics[STABILIZED].value
        abated = 10 * s.units * 50000 * mills / 1000  # building value only; land stays taxed
        assert s.revenue.abated_years == 10
        assert s.metrics[REVENUE].value == pytest.approx(gross - abated, rel=1e-3)


def test_zero_year_abatement_changes_nothing(config_copy, lot, monkeypatch):
    d, edit = config_copy
    _review_and_pin(edit, years_value=0)
    cfg = load_config(d)
    monkeypatch.setattr(engine_mod, "load_comps", lambda _cfg: _comps(cfg))
    a = analyze(cfg, lot)
    years = int(cfg.assumption("analysis_years").value)
    for s in a.scenarios:
        assert s.revenue.abated_years == 0
        assert s.metrics[REVENUE].value == pytest.approx(years * s.metrics[STABILIZED].value, rel=1e-3)


def test_exempt_parcel_pays_nothing_today_and_still_analyzes(cfg, lot):
    a = analyze(cfg, {**lot, "tax_status": cfg.tax.status.exempt_values[0]})
    today = next(m for m in a.site_context if m.id == "site.tax_today")
    status = next(m for m in a.site_context if m.id == "site.tax_status_today")
    assert today.value == 0 and status.value == 0 and status.provenance == "observed"
    assert len(a.scenarios) == len(cfg.typologies)
    unknown = next(m for m in analyze(cfg, lot).site_context if m.id == "site.tax_status_today")
    assert unknown.provenance == "placeholder"


def test_household_tax_is_inside_monthly_cost(cfg, lot):
    a = analyze(cfg, lot)
    cap = cfg.assumption("annual_capital_cost_share").value
    opex = cfg.assumption("operating_cost_per_unit_month").value
    for s in a.scenarios:
        m = s.metrics
        expected = m["affordability.dev_cost_per_unit"].value * cap / 12 + opex + m[HOME_TAX].value
        assert m["affordability.monthly_cost"].value == pytest.approx(expected, abs=2)


def test_homestead_exclusion_applies_to_owner_tenure_only(config_copy, lot):
    d, edit = config_copy
    edit("assumptions.yaml",
         lambda y: [_pin(y, k, 20000) for k in list(y["assumptions"]) if k.startswith("homestead_exclusion_")])
    cfg = load_config(d)
    S = Samples(cfg)
    typ = cfg.typologies[0]
    comps = _comps(cfg, 50000, 50000, 50000)
    owner = scenario_tax(cfg, S, typ.model_copy(update={"tenure_default": "owner"}), 2, lot, comps)
    renter = scenario_tax(cfg, S, typ.model_copy(update={"tenure_default": "renter"}), 2, lot, comps)
    assert owner.metrics[HOME_TAX].value < renter.metrics[HOME_TAX].value
    assert owner.metrics[STABILIZED].value < renter.metrics[STABILIZED].value
```

Also extend `tests/test_no_hardcoding.py::test_fake_typologies_work`: give `zeta` the key `"assessment_use_classes": ["ZETA CLASS"]` (leave `omega` without one), and add a tax.yaml edit before `load_config(d)`:
```python
    edit("tax.yaml", lambda y: y["comps"]["use_classes"].__setitem__("ZETA CLASS", {"homes": 6}))
```
and after the existing assertions:
```python
    assert {"revenue.public_horizon", "tax.per_home_monthly"} <= set(s.metrics)
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_tax.py tests/test_no_hardcoding.py -q`
Expected: new tests fail (`ImportError: cannot import name 'scenario_tax'`, `KeyError: 'revenue.public_horizon'`).

- [ ] **Step 3: Add `scenario_tax` and `site_tax_context` to `core/tax.py`** (append)

```python
@dataclass
class TaxResult:
    metrics: dict[str, Metric]
    revenue: RevenueSeries
    monthly_per_home: np.ndarray  # feeds the affordability chain in core/engine.py
    trace_household: Trace
    notes: list[str] = field(default_factory=list)


def _bodies(cfg: Config, S: Samples, trace: Trace) -> list[tuple[str, np.ndarray, np.ndarray]]:
    """(body id, millage draws, homestead exclusion draws) per taxing body."""
    out = []
    for b in cfg.tax.taxing_bodies:
        mills = S.a(b.millage, used=trace)
        excl = S.a(b.homestead_exclusion, used=trace) if b.homestead_exclusion else S.const(0)
        out.append((b.id, mills, excl))
    return out


def scenario_tax(cfg: Config, S: Samples, typ: Typology, units: int, parcel: dict, comps: dict) -> TaxResult:
    """Tax per home, stabilized annual revenue, and cumulative revenue over the
    horizon net of any REVIEWED abatement. Unreviewed programs are not applied and
    mark the horizon metric a placeholder, exactly like an unreviewed zoning rule."""
    years = int(cfg.assumption("analysis_years").value)
    units = max(units, 1)
    land = float(parcel.get("land_value_usd") or 0)
    home = per_home_assessed(cfg, S, typ, parcel.get("neighborhood"), comps)

    t_base = Trace().merge(home.trace)
    if parcel.get("land_value_usd") is not None:
        t_base.add("observed", cfg.assessment_source)
    bodies = _bodies(cfg, S, t_base)
    homestead = typ.tenure_default in cfg.tax.homestead.applies_to_tenure
    land_per_home = land / units

    # Abatement: exempt building value per home per year, per taxing body.
    t_rev = t_base.merge(Trace())
    exempt = {bid: np.zeros((years, S.n + 1)) for bid, _, _ in bodies}
    abated_years = 0
    notes: list[str] = []
    for prog in (a for a in cfg.tax.abatements if typ.use_key in a.eligible_use_keys):
        if not prog.reviewed:
            t_rev.add("placeholder", None)
            notes.append(f"{prog.label}: terms not reviewed yet; revenue shown without it.")
            continue
        yrs = np.clip(np.rint(S.a(prog.years, used=t_rev)), 0, years)  # (n+1,)
        cap = S.a(prog.exempt_assessed_cap_usd, used=t_rev)
        mask = np.arange(years)[:, None] < yrs[None, :]  # (years, n+1)
        per_home = np.where(mask, np.minimum(home.draws, cap)[None, :], 0.0)
        for bid in prog.applies_to_bodies:
            exempt[bid] = np.minimum(exempt[bid] + per_home, home.draws[None, :])
        abated_years = max(abated_years, int(yrs[0]))
        notes.append(f"{prog.label}: {int(yrs[0])} abated years applied.")

    annual_full = S.const(0)  # whole lot, per year, no abatement
    annual = np.zeros((years, S.n + 1))
    for bid, mills, excl in bodies:
        base = home.draws + land_per_home - (excl if homestead else 0)
        annual_full = annual_full + units * np.maximum(base, 0) * mills / 1000
        annual += units * np.maximum(base[None, :] - exempt[bid], 0) * mills / 1000
    per_home_month = annual_full / units / 12
    cumulative = np.vstack([np.zeros((1, S.n + 1)), np.cumsum(annual, axis=0)])

    series = RevenueSeries(
        years=list(range(years + 1)),
        value=[round(float(r[0])) for r in cumulative],
        low=[round(float(np.percentile(r[1:], 5))) for r in cumulative],
        high=[round(float(np.percentile(r[1:], 95))) for r in cumulative],
        provenance=weakest(t_rev.prov(), "modeled"),
        abated_years=abated_years,
    )
    bodies_label = ", ".join(b.label for b in cfg.tax.taxing_bodies)
    metrics = {
        "revenue.public_horizon": to_metric(
            "revenue.public_horizon", f"Public revenue over {years} years", cumulative[-1], "USD", t_rev,
            note=home.note),
        "revenue.annual_stabilized": to_metric(
            "revenue.annual_stabilized", "Property tax per year once fully taxable", annual_full, "USD/yr",
            t_base, note=f"To {bodies_label}, before any abatement."),
        "tax.per_home_monthly": to_metric(
            "tax.per_home_monthly", "Property tax per home", per_home_month, "USD/mo", t_base,
            note="Assessed value x millage; homestead exclusion applied to owner-occupied types."),
    }
    return TaxResult(metrics=metrics, revenue=series, monthly_per_home=per_home_month,
                     trace_household=t_base, notes=notes)


def site_tax_context(cfg: Config, S: Samples, parcel: dict) -> list[Metric]:
    """Does the lot pay tax today, and roughly what. Lot-level, so site context."""
    status = parcel.get("tax_status")
    known = status is not None
    exempt = known and str(status) in cfg.tax.status.exempt_values
    obs = Trace({"observed"}, {cfg.assessment_source})
    t = Trace({"observed"}, {cfg.assessment_source})
    total_mills = S.const(0)
    for b in cfg.tax.taxing_bodies:
        total_mills = total_mills + S.a(b.millage, used=t)
    land = float(parcel.get("land_value_usd") or 0)
    today = S.const(0) if exempt else land * total_mills / 1000
    return [
        to_metric("site.tax_status_today", "Pays property tax today", S.const(0 if exempt else 1), "yes/no", obs,
                  note=f"Assessment tax status: {status}" if known else "Tax status not in the parcel index yet",
                  provenance="observed" if known else "placeholder"),
        to_metric("site.tax_today", "Property tax this lot pays today (vacant)", today, "USD/yr", t,
                  note="Assessed land value x combined millage; zero when the parcel is tax-exempt.",
                  provenance=None if known else "placeholder"),
    ]
```

- [ ] **Step 4: Integrate into `core/engine.py`**

Import: after `from core.metrics import ...` add
```python
from core.tax import RevenueSeries, load_comps, scenario_tax, site_tax_context
```

In `class Scenario`, after `carbon: CarbonSeries`, add `revenue: RevenueSeries`.

In `analyze`, after `rules = load_rules(cfg)` add `comps = load_comps(cfg)`.

After the hazards `for flag, spec in hazards_cfg.items(): ...` loop (before `# --- Shared affordability inputs`), add:
```python
    site_context.extend(site_tax_context(cfg, S, parcel))
```

Replace
```python
        cap = S.a("annual_capital_cost_share", used=t_cost)
        opex = S.a("operating_cost_per_unit_month", used=t_cost)
        monthly = per_unit * cap / 12 + opex
        t_aff = t_cost.merge(t_inc)
```
with
```python
        cap = S.a("annual_capital_cost_share", used=t_cost)
        opex = S.a("operating_cost_per_unit_month", used=t_cost)
        # Property tax is its own line, from assessed value and millage, so the
        # cost of living here is not hiding a tax guess inside a flat operating cost.
        tax = scenario_tax(cfg, S, typ, units, parcel, comps)
        notes.extend(tax.notes)
        monthly = per_unit * cap / 12 + opex + tax.monthly_per_home
        t_aff = t_cost.merge(tax.trace_household).merge(t_inc)
```

In the `metrics = {...}` dict, add `**tax.metrics,` on the line before `"units.count": ...`.

In `scenarios.append(Scenario(...))`, add `revenue=tax.revenue,` after `carbon=carbon,`.

- [ ] **Step 5: Run the tests**

Run: `uv run pytest tests/test_tax.py tests/test_no_hardcoding.py tests/test_engine.py tests/test_explain.py -q`
Expected: all pass.

Run: `uv run pytest -q 2>&1 | tail -3`
Expected: only the 2 known failures.

- [ ] **Step 6: Lint and commit**

```bash
uv run ruff check .
git add core/tax.py core/engine.py tests/test_tax.py tests/test_no_hardcoding.py
git commit -m "core: property tax per home, public revenue over the horizon net of reviewed abatement, lot tax status

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 4: Tension flags in the engine

**Files:**
- Modify: `core/engine.py`
- Test: `tests/test_tax.py`

- [ ] **Step 1: Write the failing test** (append to `tests/test_tax.py`)

```python
from core.engine import tension_flags
from core.metrics import Metric


def _m(mid, v):
    return Metric(id=mid, label=mid, value=v, low=v, high=v, unit="x", provenance="modeled", sourceIds=[])


def test_tension_flag_fires_only_when_top_and_bottom_coincide(cfg):
    flag = cfg.tension_flags[0]
    crit = {c.id: c for c in cfg.criteria}
    top, bottom = crit[flag.top_on], crit[flag.bottom_on[0]]
    others = [c for c in cfg.criteria if c.id not in (top.id, bottom.id)]

    def option(top_v, bottom_v):
        ms = {top.metric_id: _m(top.metric_id, top_v), bottom.metric_id: _m(bottom.metric_id, bottom_v)}
        for c in others:
            ms[c.metric_id] = _m(c.metric_id, 1.0)
        return ms

    hi_top, lo_top = (10, 1) if top.direction == "higher_is_better" else (1, 10)
    worst_bottom, best_bottom = (10, 1) if bottom.direction == "lower_is_better" else (1, 10)

    got = tension_flags(cfg, {"a": option(hi_top, worst_bottom), "b": option(lo_top, best_bottom)})
    assert [(f.id, f.typology_id, f.bottom_on) for f in got] == [(flag.id, "a", [bottom.id])]
    assert tension_flags(cfg, {"a": option(hi_top, best_bottom), "b": option(lo_top, worst_bottom)}) == []
    assert tension_flags(cfg, {"a": option(hi_top, worst_bottom)}) == []


def test_analysis_carries_tension_flags(cfg, lot):
    a = analyze(cfg, lot)
    assert isinstance(a.tension_flags, list)
    for f in a.tension_flags:
        assert f.typology_id in a.rankable_typology_ids
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_tax.py -q -k tension`
Expected: `ImportError: cannot import name 'tension_flags'`.

- [ ] **Step 3: Implement in `core/engine.py`**

After `class CarbonSeries`, add:
```python
class TensionFlagResult(BaseModel):
    """One option best on one criterion and worst on another (criteria.yaml
    tension_flags). Single-criterion ranks involve no weights: this is evidence."""

    id: str
    label: str
    message: str
    typology_id: str
    top_on: str
    bottom_on: list[str]
```

In `class Analysis`, after `excluded_typology_ids: list[str] = []`, add:
```python
    tension_flags: list[TensionFlagResult] = []
```

Add before `def work_backwards`:
```python
def tension_flags(cfg: Config, metrics_by_option: dict[str, dict[str, Metric]]) -> list[TensionFlagResult]:
    """Options best on `top_on` that are also worst on any of `bottom_on`, for
    every flag criteria.yaml declares. Needs at least two options to compare."""
    if len(metrics_by_option) < 2:
        return []
    crit = {c.id: c for c in cfg.criteria}

    def best_worst(cid: str) -> tuple[set[str], set[str]]:
        c = crit[cid]
        vals = {oid: m[c.metric_id].value for oid, m in metrics_by_option.items()}
        lo, hi = min(vals.values()), max(vals.values())
        if lo == hi:
            return set(), set()
        best_v, worst_v = (hi, lo) if c.direction == "higher_is_better" else (lo, hi)
        return {o for o, v in vals.items() if v == best_v}, {o for o, v in vals.items() if v == worst_v}

    out: list[TensionFlagResult] = []
    for f in cfg.tension_flags:
        best, _ = best_worst(f.top_on)
        for oid in sorted(best):
            hit = [cid for cid in f.bottom_on if oid in best_worst(cid)[1]]
            if hit:
                out.append(TensionFlagResult(id=f.id, label=f.label, message=f.message, typology_id=oid,
                                             top_on=f.top_on, bottom_on=hit))
    return out
```

In `analyze`, before `n_placeholder = ...`, add:
```python
    flags = tension_flags(cfg, {s.typology_id: s.metrics for s in scenarios if s.eligible and s.form_fits})
```
and add `tension_flags=flags,` to the `Analysis(...)` constructor.

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_tax.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
uv run ruff check .
git add core/engine.py tests/test_tax.py
git commit -m "core: config-driven tension flags — best on one criterion, worst on another

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 5: Plans sum revenue across building types

**Files:**
- Modify: `core/plan.py`
- Test: `tests/test_tax.py`

- [ ] **Step 1: Write the failing test** (append)

```python
def test_plan_sums_revenue_across_building_types(cfg, lot):
    from core.plan import Placement, analyze_plan

    a, b = cfg.typologies[0], cfg.typologies[-1]
    r = analyze_plan(cfg, lot, [Placement(typology_id=a.id, count=1), Placement(typology_id=b.id, count=1)])
    parts = analyze(cfg, lot, homes_override={a.id: a.building.homes, b.id: b.building.homes})
    assert r.metrics[REVENUE].value == pytest.approx(sum(s.metrics[REVENUE].value for s in parts.scenarios), rel=1e-6)
    assert r.revenue.value[-1] == pytest.approx(sum(s.revenue.value[-1] for s in parts.scenarios), abs=2)
    assert len(r.revenue.years) == len(r.carbon.years)
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_tax.py -q -k plan_sums`
Expected: FAIL (`AttributeError: 'PlanResult' object has no attribute 'revenue'` or a validation error).

- [ ] **Step 3: Implement in `core/plan.py`**

Change the import line `from core.metrics import Metric, Samples, weakest` to stay, and add `from core.tax import RevenueSeries`.

Change `SUMMED` to:
```python
# Which metrics add up across building types; everything else is a per-home
# measure and is averaged by homes. Revenue is what the whole lot yields.
SUMMED = {"demand.units_serving_need", "infrastructure.load_index", "units.count",
          "revenue.public_horizon", "revenue.annual_stabilized"}
```

In `class PlanResult`, after `carbon: CarbonSeries`, add `revenue: RevenueSeries`.

In `analyze_plan`, after the carbon block, add:
```python
    # Revenue: the lot's total, so the per-type series add.
    rev = [by_id[tid].revenue for tid in homes]
    def rsum(attr: str) -> list[float]:
        return [round(sum(getattr(r, attr)[i] for r in rev)) for i in range(len(rev[0].years))]
    revenue = RevenueSeries(years=rev[0].years, value=rsum("value"), low=rsum("low"), high=rsum("high"),
                            provenance=weakest(*(r.provenance for r in rev)),
                            abated_years=max(r.abated_years for r in rev))
```
and add `revenue=revenue,` to the `PlanResult(...)` constructor.

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_tax.py tests/test_plan.py -q`
Expected: all pass except the known `test_prohibited_building_type_is_flagged_and_plan_is_excluded`.

- [ ] **Step 5: Commit**

```bash
uv run ruff check .
git add core/plan.py tests/test_tax.py
git commit -m "core: mixed plans sum public revenue across building types

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 6: Independence guardrail

**Files:**
- Test: `tests/test_tax.py`

- [ ] **Step 1: Write the test** (append)

```python
import json
import random

import numpy as np

from core.config import ROOT
from core.scoring import normalize

PARCELS = ROOT / "data" / "processed" / "parcels.json"


def _lots(lot):
    if PARCELS.exists():
        parcels = list(json.loads(PARCELS.read_text(encoding="utf-8"))["parcels"].values())
        return random.Random(7).sample(parcels, 60)
    return [{**lot, "lot_area_sf": a, "land_value_usd": v}
            for a, v in ((3000, 5000), (5000, 10000), (9000, 30000), (20000, 80000))]


def test_public_revenue_is_not_a_restatement_of_another_criterion(cfg, lot):
    """Per lot, not pooled: the `opportunity` failure was a within-lot cancellation,
    and pooling across lots would average it away."""
    max_r = cfg.assumption("criterion_independence_max_corr").value
    new = next(c for c in cfg.criteria if c.metric_id == REVENUE)
    others = [c for c in cfg.criteria if c.id != new.id]
    crits = [new, *others]
    hib = np.array([c.direction == "higher_is_better" for c in crits])
    worst: tuple[float, str, str] = (0.0, "", "")
    checked = 0
    for p in _lots(lot):
        rows = [s for s in analyze(cfg, p).scenarios if s.eligible and s.form_fits]
        if len(rows) < 3:
            continue
        n = normalize(np.array([[s.metrics[c.metric_id].value for c in crits] for s in rows]), hib)
        x = n[:, 0]
        if x.max() == x.min():
            continue
        for j, c in enumerate(others, start=1):
            y = n[:, j]
            if y.max() == y.min():
                continue
            r = abs(float(np.corrcoef(x, y)[0, 1]))
            checked += 1
            if r > worst[0]:
                worst = (r, c.id, str(p.get("id")))
    assert checked > 0
    assert worst[0] < max_r, f"{new.id} vs {worst[1]}: |r|={worst[0]:.4f} on parcel {worst[2]}"
```

- [ ] **Step 2: Run it**

Run: `uv run pytest tests/test_tax.py -q -k restatement -s`
Expected: PASS. If it fails, the message names the criterion and parcel; do **not** raise the threshold — investigate whether the comps/placeholder per-home values collapsed to a constant across typologies.

- [ ] **Step 3: Commit**

```bash
git add tests/test_tax.py
git commit -m "tests: public revenue must not be an affine restatement of another criterion, per lot

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 7: Pipeline — comps table

**Files:**
- Modify: `pipeline/adapters/ckan.py`, `pipeline/build_parcels.py`
- Create: `pipeline/steps/comps.py`, `pipeline/build_comps.py`
- Test: `tests/test_comps_step.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_comps_step.py`:
```python
"""Comps aggregation is pure: rows in, table out. Network lives in pipeline/build_comps.py."""

from pipeline.steps.comps import aggregate_comps, per_home_values


def _rows(use_class, n, value, hood, year=2015):
    return [{"id": f"{use_class}{i}", "use_class": use_class, "building_value": value,
             "year_built": year, "neighborhood": hood} for i in range(n)]


def test_neighborhood_needs_min_comps_else_citywide_only(cfg):
    typ = cfg.typologies[0]
    uc = typ.assessment_use_classes[0]
    k = cfg.tax.comps.min_comps
    rows = _rows(uc, k, 100000, "Big") + _rows(uc, k - 1, 200000, "Small")
    t = aggregate_comps(cfg, rows)["by_typology"][typ.id]
    assert set(t["neighborhoods"]) == {"Big"}
    assert t["neighborhoods"]["Big"]["n"] == k
    assert t["citywide"]["n"] == 2 * k - 1
    assert t["neighborhoods"]["Big"]["low"] <= t["neighborhoods"]["Big"]["value"] <= t["neighborhoods"]["Big"]["high"]


def test_old_buildings_and_unknown_classes_are_not_comps(cfg):
    uc = cfg.typologies[0].assessment_use_classes[0]
    rows = _rows(uc, 5, 100000, "X", year=cfg.tax.comps.built_since_year - 1)
    rows.append({"id": "z", "use_class": "NOT A CLASS", "building_value": 1, "year_built": 2020, "neighborhood": "X"})
    rows.append({"id": "nv", "use_class": uc, "building_value": None, "year_built": 2020, "neighborhood": "X"})
    assert dict(per_home_values(cfg, rows)) == {}


def test_unit_band_widens_the_per_home_range(cfg):
    uc, spec = next((u, c) for u, c in cfg.tax.comps.use_classes.items() if c.low is not None and c.high is not None)
    typ = next(t for t in cfg.typologies if uc in t.assessment_use_classes)
    rows = _rows(uc, cfg.tax.comps.min_comps, 1_200_000, "H")
    row = aggregate_comps(cfg, rows)["by_typology"][typ.id]["neighborhoods"]["H"]
    assert row["value"] == round(1_200_000 / spec.homes)
    assert row["low"] == round(1_200_000 / spec.high)
    assert row["high"] == round(1_200_000 / spec.low)


def test_too_few_comps_citywide_gives_no_row(cfg):
    typ = cfg.typologies[0]
    rows = _rows(typ.assessment_use_classes[0], cfg.tax.comps.min_comps - 1, 100000, "X")
    t = aggregate_comps(cfg, rows)["by_typology"][typ.id]
    assert t["citywide"] is None and t["neighborhoods"] == {}
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_comps_step.py -q`
Expected: `ModuleNotFoundError: No module named 'pipeline.steps.comps'`.

- [ ] **Step 3: Create `pipeline/steps/comps.py`**

```python
"""Assessment comparables: what the county assesses EXISTING buildings of each
housing type at, per home, by neighborhood. Pure functions; no I/O."""

from __future__ import annotations

import statistics
from collections import defaultdict

from core.config import Config

# (neighborhood, per-home value at the band midpoint, at the band's low edge, at its high edge)
Comp = tuple[str | None, float, float, float]


def per_home_values(cfg: Config, rows: list[dict]) -> dict[str, list[Comp]]:
    """typology id -> one Comp per qualifying row of that typology's use classes.

    A multi-unit class is a unit band, so one parcel's per-home value is
    building_value / homes with homes anywhere in the band. Dividing by the low
    edge gives the highest per-home value the row supports, by the high edge the
    lowest; those bound the range the engine draws from."""
    classes = cfg.tax.comps.use_classes
    since = cfg.tax.comps.built_since_year
    typologies_for: dict[str, list[str]] = defaultdict(list)
    for t in cfg.typologies:
        for uc in t.assessment_use_classes:
            typologies_for[uc].append(t.id)
    out: dict[str, list[Comp]] = defaultdict(list)
    for r in rows:
        uc = r.get("use_class")
        if uc not in classes:
            continue
        try:
            value = float(r.get("building_value") or 0)
            year = int(float(r.get("year_built") or 0))
        except (TypeError, ValueError):
            continue
        if value <= 0 or year < since:
            continue
        spec = classes[uc]
        lo_homes, hi_homes = spec.band()
        for tid in typologies_for[uc]:
            out[tid].append((r.get("neighborhood"), value / spec.homes, value / lo_homes, value / hi_homes))
    return out


def _quantile(sorted_vals: list[float], q: float) -> float:
    pos = q * (len(sorted_vals) - 1)
    lo, hi = int(pos), min(int(pos) + 1, len(sorted_vals) - 1)
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (pos - lo)


def _summary(comps: list[Comp], q: tuple[float, float]) -> dict:
    """Median of the midpoint values; `low` is the lower quantile of the smallest
    per-home reading each row supports, `high` the upper quantile of the largest.
    With quantiles straddling 0.5 this guarantees low <= value <= high."""
    return {
        "value": round(statistics.median(c[1] for c in comps)),
        "low": round(_quantile(sorted(c[3] for c in comps), q[0])),
        "high": round(_quantile(sorted(c[2] for c in comps), q[1])),
        "n": len(comps),
    }


def aggregate_comps(cfg: Config, rows: list[dict]) -> dict:
    """The table core/tax.py reads: per typology, a citywide row and one row per
    neighborhood with at least `min_comps` comps. Row keys: id, use_class,
    building_value, year_built, neighborhood."""
    rule = cfg.tax.comps
    table: dict = {}
    for tid, comps in per_home_values(cfg, rows).items():
        by_hood: dict[str, list[Comp]] = defaultdict(list)
        for c in comps:
            if c[0]:
                by_hood[c[0]].append(c)
        table[tid] = {
            "citywide": _summary(comps, rule.quantiles) if len(comps) >= rule.min_comps else None,
            "neighborhoods": {h: _summary(v, rule.quantiles) for h, v in sorted(by_hood.items())
                              if len(v) >= rule.min_comps},
        }
    return {"config_hash": cfg.hash, "built_since_year": rule.built_since_year,
            "min_comps": rule.min_comps, "by_typology": table}
```

- [ ] **Step 4: Run the step tests**

Run: `uv run pytest tests/test_comps_step.py -q`
Expected: 4 passed.

- [ ] **Step 5: Key the CKAN cache by query, not just source**

In `pipeline/adapters/ckan.py`, add `import hashlib` at the top, and in `CkanDatastore.fetch` replace
```python
        cache = RAW_DIR / f"{self.source_id}.json"
```
with
```python
        # Two callers can read the same table with different columns or filters
        # (the parcel index wants vacant lots; comps want built ones). A cache keyed
        # on the source alone would hand the second caller the first one's rows.
        sig = hashlib.sha256(json.dumps([sorted(self.fields), self.filters], sort_keys=True).encode()).hexdigest()[:8]
        cache = RAW_DIR / f"{self.source_id}-{sig}.json"
```
(First run after this re-downloads the assessment and centroid tables once; `data/raw/` is gitignored.)

- [ ] **Step 6: Carry `tax_status` into the parcel index**

In `pipeline/build_parcels.py`, in the `cols = [...]` list, add `"tax_status"` after `"owner_type"`.

- [ ] **Step 7: Create `pipeline/build_comps.py`**

```python
"""Build assessment comparables for core/tax.py.

    uv run python -m pipeline.build_comps

Reads the same county assessment table the parcel index uses, keeps only the use
classes tax.yaml declares, joins each comp to its city neighborhood through the
parcel centroid file, and writes the comps table (path: tax.yaml comps.file).
Needs `uv sync --group pipeline`.
"""

from __future__ import annotations

import json
import logging
import re

import pandas as pd

from core.config import ROOT, Config, load_config
from pipeline.adapters.ckan import CkanDatastore
from pipeline.steps.comps import aggregate_comps

log = logging.getLogger("pipeline")


def build(cfg: Config) -> dict:
    pc = cfg.parcels
    comps = cfg.tax.comps
    use_col = next(k for k, v in comps.fields.items() if v == "use_class")
    res = CkanDatastore(pc["assessments_source"], list(comps.fields), {use_col: list(comps.use_classes)}).fetch(cfg)
    if not res.ok:
        raise SystemExit("assessments unavailable — cannot build comps")
    df = pd.DataFrame(res.data).rename(columns=comps.fields)
    muni = re.compile(pc["municipality_pattern"])
    df = df[df["municipality"].fillna("").str.contains(muni)].drop(columns=["municipality"])

    cf = pc["centroid_fields"]
    cent = CkanDatastore(pc["centroids_source"], list(cf), pc["centroids_filter"]).fetch(cfg)
    if cent.ok:
        cdf = pd.DataFrame(cent.data).rename(columns=cf)[["id", "neighborhood"]].drop_duplicates("id")
        df = df.merge(cdf, on="id", how="left")
    else:
        df["neighborhood"] = None
    rows = df.astype(object).where(df.notna(), None).to_dict(orient="records")

    table = aggregate_comps(cfg, rows)
    out = ROOT / comps.file
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(table, indent=1), encoding="utf-8")
    for tid, t in table["by_typology"].items():
        cw = t["citywide"] or {}
        log.info("%s: citywide n=%s median=%s; %d neighborhoods with >= %d comps",
                 tid, cw.get("n"), cw.get("value"), len(t["neighborhoods"]), comps.min_comps)
    log.info("wrote %s", out)
    return table


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    build(load_config())
```

- [ ] **Step 8: Build the comps table (network; several minutes)**

Run: `uv run python -m pipeline.build_comps`
Expected: log lines per typology with a citywide `n` in the thousands for single-family classes, and `wrote .../data/processed/assessment_comps.json`. If a typology shows `citywide n=None`, its use classes had fewer than `min_comps` recent buildings citywide — note it for LIMITATIONS, do not lower `min_comps` to hide it.

- [ ] **Step 9: Rebuild the parcel index so `tax_status` is present**

Run: `uv run python -m pipeline.build_parcels`
Expected: re-downloads the two tables (new cache key), then `indexed 22,xxx vacant parcels`. Then:

Run: `uv run python -c "import json;p=json.load(open('data/processed/parcels.json',encoding='utf-8'))['parcels'];print(sum(1 for r in p.values() if r.get('tax_status')), 'of', len(p), 'have tax_status')"`
Expected: nearly all.

- [ ] **Step 10: Whole suite (comps now observed)**

Run: `uv run pytest -q 2>&1 | tail -3`
Expected: only the 2 known failures. In particular `test_public_revenue_is_not_a_restatement_of_another_criterion` now runs on 60 real parcels with observed comps.

- [ ] **Step 11: Commit**

```bash
uv run ruff check .
git add pipeline/adapters/ckan.py pipeline/build_parcels.py pipeline/steps/comps.py pipeline/build_comps.py tests/test_comps_step.py data/processed/assessment_comps.json data/processed/parcels.json data/processed/pipeline_report.json web/public/data/parcels.geojson
git commit -m "pipeline: assessment comps by housing type and neighborhood; tax status in the parcel index

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 8: `/unknowns` and LIMITATIONS auto-section

**Files:**
- Modify: `server/app.py`, `pipeline/docs.py`
- Test: `tests/test_tax.py`

- [ ] **Step 1: Write the failing test** (append)

```python
def test_unknowns_lists_unreviewed_tax_terms():
    from fastapi.testclient import TestClient
    from server.app import app

    u = TestClient(app).get("/api/unknowns").json()
    assert "unreviewed_tax_terms" in u
    assert all({"id", "label"} <= set(t) for t in u["unreviewed_tax_terms"])
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_tax.py -q -k unknowns`
Expected: FAIL (`KeyError`/assertion on `unreviewed_tax_terms`).

- [ ] **Step 3: Extend `/unknowns` in `server/app.py`**

In the returned dict of `unknowns()`, after `"unreviewed_districts": [...]`, add:
```python
        "unreviewed_tax_terms": [
            {"id": a.id, "label": a.label, "note": a.note} for a in cfg.tax.abatements if not a.reviewed],
```

- [ ] **Step 4: Extend `limitations_auto` in `pipeline/docs.py`**

Before the `return "\n".join([...])`, add:
```python
    tax_unreviewed = [a.label for a in cfg.tax.abatements if not a.reviewed]
    comps_path = ROOT / cfg.tax.comps.file
    comps = json.loads(comps_path.read_text(encoding="utf-8")) if comps_path.exists() else None
    if comps:
        cov = "; ".join(f"{tid}: {len(t['neighborhoods'])} neighborhoods"
                        + ("" if t["citywide"] else ", no citywide row")
                        for tid, t in comps["by_typology"].items())
        comps_line = (f"- **Assessment comps (buildings since {comps['built_since_year']}, at least "
                      f"{comps['min_comps']} per neighborhood):** {cov}.")
    else:
        comps_line = "- **Assessment comps:** not built; per-home assessed values are placeholders."
```
and add two entries to the list before `END`:
```python
        (f"- **Tax terms not yet reviewed ({len(tax_unreviewed)}):** {', '.join(tax_unreviewed) or 'none'}. "
         "Millage and homestead figures stay placeholders until sourced (listed above)."),
        comps_line,
```

- [ ] **Step 5: Run the test and regenerate the docs**

Run: `uv run pytest tests/test_tax.py tests/test_api.py -q`
Expected: pass.

Run: `uv run python -m pipeline.docs`
Expected: `wrote docs/SOURCES.md and updated docs/LIMITATIONS.md`; the auto block now has the two new lines and 4 more "Sources not yet connected".

- [ ] **Step 6: Commit**

```bash
uv run ruff check .
git add server/app.py pipeline/docs.py tests/test_tax.py docs/SOURCES.md docs/LIMITATIONS.md
git commit -m "api+docs: unreviewed tax terms and comps coverage in /unknowns and LIMITATIONS

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 9: Web — types, receipt extras, tension callout, memo, unknowns

**Files:**
- Modify: `web/src/types.ts`, `web/src/lib/plan.ts`, `web/src/components/AnalysisPanel.tsx`, `web/src/components/MemoModal.tsx`

- [ ] **Step 1: Types (`web/src/types.ts`)**

After `export interface CarbonSeries {...}` add:
```ts
export interface RevenueSeries extends CarbonSeries {
  abated_years: number
}

export interface TensionFlag {
  id: string
  label: string
  message: string
  typology_id: string
  top_on: string
  bottom_on: string[]
}
```
In `Scenario` add `revenue: RevenueSeries` after `carbon: CarbonSeries`. In `PlanResult` add `revenue: RevenueSeries` after `carbon: CarbonSeries`. In `Analysis` add `tension_flags: TensionFlag[]` after `placeholder_count: number`. In `Config` add after `assumptions: ...`:
```ts
  tension_flags: { id: string; label: string; top_on: string; bottom_on: string[]; message: string }[]
  tax: {
    taxing_bodies: { id: string; label: string }[]
    abatements: { id: string; label: string; reviewed: boolean; note?: string | null }[]
  }
```
In `Unknowns` add `unreviewed_tax_terms: { id: string; label: string; note: string | null }[]`.

- [ ] **Step 2: Pool (`web/src/lib/plan.ts`)**

Import `RevenueSeries` from `../types`. In `interface Option` add `revenue: RevenueSeries` after `carbon: CarbonSeries`. In `buildPool`, add `revenue: s.revenue,` to the pure option literal (after `carbon: s.carbon,`) and `revenue: plan.revenue,` to `own` (after `carbon: plan.carbon,`).

- [ ] **Step 3: Compare tab and unknowns (`web/src/components/AnalysisPanel.tsx`)**

Above `function CompareTab`, add:
```ts
// Metric ids from core/tax.py shown under "Your plan" beside the criteria. They
// are not criteria (never weighted), so config.criteria does not list them.
const RECEIPT_EXTRAS = ['revenue.annual_stabilized', 'tax.per_home_monthly']
```
Inside the plan block, directly after the `<div className="col tight">{config.criteria.map(...)}</div>` that renders the plan's MetricBoxes, add:
```tsx
            <div className="col tight">
              {RECEIPT_EXTRAS.filter((id) => plan.metrics[id]).map((id) => (
                <MetricBox key={id} m={plan.metrics[id]} />
              ))}
            </div>
```
In the ranking column, directly after the `{ranking.excluded.length > 0 && (...)}` block, add:
```tsx
          {analysis.tension_flags.map((f) => (
            <div key={`${f.id}-${f.typology_id}`} className="note-box small">
              <strong>{f.label}:</strong> {labelOf(f.typology_id)}. {f.message}
            </div>
          ))}
```
In `UnknownsTab`, before `<div className="h-card">Placeholder numbers ...`, add:
```tsx
      <div className="h-card">Tax terms not yet reviewed ({u.unreviewed_tax_terms.length})</div>
      {u.unreviewed_tax_terms.map((t) => (
        <div key={t.id} className="small unk-row">
          {t.label}
          {t.note && <span className="muted"> — {t.note}</span>}
        </div>
      ))}
```

- [ ] **Step 4: Memo (`web/src/components/MemoModal.tsx`)**

After the `{ranking.excluded.length > 0 && <p ...>}` line, add:
```tsx
        {analysis.tension_flags.map((f) => (
          <p key={`${f.id}-${f.typology_id}`} className="small">
            <strong>{f.label}:</strong> {config.typologies.find((t) => t.id === f.typology_id)?.label ?? f.typology_id}. {f.message}
          </p>
        ))}
```

- [ ] **Step 5: Typecheck, lint, guard test**

Run: `cd web && npx tsc -b && npm run lint && cd ..`
Expected: no errors.

Run: `uv run pytest tests/test_no_hardcoding.py -q`
Expected: pass (no criterion, typology, status or source id quoted in `web/src`).

- [ ] **Step 6: Commit**

```bash
git add web/src/types.ts web/src/lib/plan.ts web/src/components/AnalysisPanel.tsx web/src/components/MemoModal.tsx
git commit -m "web: revenue and tax on the receipt, tension flags in compare and memo, unreviewed tax terms

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 10: Documentation and spec reconciliation

**Files:**
- Modify: `docs/METHODS.md`, `docs/LIMITATIONS.md`, `docs/AI_DISCLOSURE.md`, `README.md`, `docs/superpowers/specs/2026-09-26-tax-metrics-design.md`

- [ ] **Step 1: `docs/METHODS.md`**

In "Cost and affordability", change the `monthly_cost` line to:
```
    monthly_cost   = dev_cost / homes × annual_capital_cost_share / 12 + operating_cost_per_unit_month + tax_per_home_month
```
and add after the block: `operating_cost_per_unit_month no longer includes property tax; see "Property tax" below.`

In the Criteria table add a row:
```
| Public revenue | Σ over the horizon of the parcel's property tax, net of a reviewed abatement (see below) | higher better |
```

After the "Two changes on 2026-09-26" paragraphs, add:
```markdown
**A criterion was added on 2026-09-26: "Public revenue."** It is `homes × per-home
assessed value + land value`, times millage, summed over the horizon. It survives
the test that removed "job access" because the per-home assessed value differs by
housing type (it comes from county comps of that type) and is not derived from
development cost. `tests/test_tax.py` checks on real lots that its normalized
column is not an affine restatement of any other criterion's.
```

Add a new section before "## Scoring":
```markdown
## Property tax

Structure in `tax.yaml`; every number in `assumptions.yaml` (spec:
`docs/superpowers/specs/2026-09-26-tax-metrics-design.md`).

**Assessed value comes from observed county comparables, never from cost.**
Allegheny County assessments are base-year values, not current prices, so a
cost-derived assessment would overstate every option by about 2× and would
duplicate the cost criterion besides. `uv run python -m pipeline.build_comps`
takes every city building in each housing type's assessment use classes
(`typologies.yaml: assessment_use_classes`) built since `comps.built_since_year`,
divides its assessed building value by the homes on the parcel (a band midpoint
for multi-unit classes, with the band edges widening the range), and keeps the
median and interquartile range per neighborhood (at least `min_comps` comps) and
citywide. The engine uses the neighborhood row, else the citywide row and says
so, else a placeholder assumption.

    assessed_home_b   = max(building_per_home + land_value / homes − homestead_b, 0)   homestead_b only for owner-occupied types
    annual_full       = Σ_bodies homes × assessed_home_b × millage_b / 1000
    tax_per_home_month= annual_full / homes / 12                                          → part of monthly_cost
    exempt_b(y)       = min(building_per_home, cap) for y ≤ abatement years, else 0      only for a REVIEWED program that names body b
    annual(y)         = Σ_bodies homes × max(assessed_home_b − exempt_b(y), 0) × millage_b / 1000
    revenue_horizon   = Σ_y annual(y)                                                     → criterion "Public revenue"

Millage is in mills (tax per $1,000 of assessed value). An unreviewed abatement
program is not applied and marks horizon revenue a placeholder — the same rule as
an unreviewed zoning rule. Site context shows whether the lot pays tax today
(county tax status) and roughly what (land value × millage; zero if exempt).

**Tension flags** (`criteria.yaml: tension_flags`). The option best on one
criterion that is also worst on another is named in the receipt and the memo. A
rank on a single criterion involves no weights, so the engine computes it.

**Review checklist (a person, not the model).** City, School District and County
millage and homestead exclusions → `assumptions.yaml` (`millage_*`,
`homestead_exclusion_*`): set value/low/high, set `source`, flip provenance to
observed. Abatement terms → `tax.yaml: abatements` (`code_section`, `quote`,
`reviewed: true`) and `assumptions.yaml` (`abatement_years`,
`abatement_exempt_assessed_cap_usd`).
```

- [ ] **Step 2: `docs/LIMITATIONS.md`** — in "What it gets wrong, or can't know", replace the "Rent needed to cover cost…" bullet's last sentence with `It is not a pro forma: no financing structure, tax credits or market rents; a reviewed abatement enters only the public-revenue side.` and add these bullets:

```markdown
- **Property tax figures are placeholders until reviewed.** Millage, homestead
  exclusions and abatement terms are labeled stand-ins in `assumptions.yaml` and
  `tax.yaml`. We do not write tax law from memory; a teammate verifies each
  against the published rate or ordinance. The unreviewed abatement is not
  applied.
- **Assessed values are base-year comps of existing buildings.** A new building
  is assessed at its base-year-equivalent value; recent comps (since
  `tax.yaml: comps.built_since_year`) stand in for it. Assessment appeals, which
  materially move real bills in Allegheny County, are not modeled.
- **Multi-unit comps rest on a unit band.** The county's use classes say 5–19,
  20–39 or 40+ units, not a count. The 40+ band has no upper edge; its cap is a
  documented choice in `tax.yaml` and the weakest number in the tax module.
- **No reassessment spillover.** We do not estimate how new construction changes
  neighbors' assessments. That would be a causal displacement claim.
- **No Low-Income Housing Tax Credits.** LIHTC is a competitive PHFA allocation
  we cannot model defensibly yet; it is named as a next step.
```

- [ ] **Step 3: `docs/AI_DISCLOSURE.md`** — under "AI used to build Lotline", add:

```markdown
- Claude Code drafted the property tax structure (`data/config/tax.yaml`), the
  comps pipeline and the stand-in values in `assumptions.yaml`. It did **not**
  write millage rates or abatement terms from memory: every such value is a
  labeled placeholder until a teammate verifies it against the published rate or
  ordinance, the same review rule as zoning.
```

- [ ] **Step 4: `README.md`**

Under "What it does → Compare", add a bullet:
```markdown
  - public revenue to the City, school district and county over the horizon,
    net of any reviewed abatement, with a "high revenue, high exclusion" flag
    when the top-revenue option is also the least affordable;
```
In "Human in the loop", append: `Tax law gets the same treatment: millage and abatement terms are placeholders until a teammate verifies them (`data/config/tax.yaml`, `assumptions.yaml`).`
In "Run it", after the `pipeline.build_parcels` line, add:
```bash
uv run python -m pipeline.build_comps     # assessed-value comps per housing type and neighborhood
```
In "Next steps", add:
```markdown
5. Verify City, School District and County millage, homestead exclusions and the
   residential abatement terms; then model LIHTC in Work backwards.
```

- [ ] **Step 5: Reconcile the spec**

In `docs/superpowers/specs/2026-09-26-tax-metrics-design.md`:
- §5.1: replace the first paragraph with: `Every number (millage per body, homestead exclusions, abatement years and cap) is an assumptions.yaml entry referenced from tax.yaml by key, so it carries a range, provenance and source and flows through Samples, dependsOn, inquiries and the LIMITATIONS count. tax.yaml holds structure and legal terms; an abatement program carries reviewed: false until a person verifies it. "Reviewed" for a rate means its assumption is no longer a placeholder. The common level ratio is dropped: it converts market to assessed value, and the comps are already assessed.` Remove the `common_level_ratio` block from the YAML sketch.
- §9 test 1: replace the threshold sentence with: `The threshold is 0.999: an affine restatement gives |r| = 1 to machine precision, while two criteria that merely share home count as a driver land near 0.99 on lots where one option is far denser than the rest — a fact about the lot, not a defect.`
- Status line: `Status: implemented 2026-09-26 (plan: docs/superpowers/plans/2026-09-26-tax-metrics.md)`.

- [ ] **Step 6: Commit**

```bash
git add docs/METHODS.md docs/LIMITATIONS.md docs/AI_DISCLOSURE.md README.md docs/superpowers/specs/2026-09-26-tax-metrics-design.md
git commit -m "docs: property tax methods, limitations, review checklist, AI disclosure

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 11: Final verification

- [ ] **Step 1: Everything**

```bash
uv run pytest -q 2>&1 | tail -4
uv run ruff check .
cd web && npx tsc -b && npm run lint && cd ..
```
Expected: pytest shows only the 2 pre-existing failures; ruff clean; tsc and oxlint clean.

- [ ] **Step 2: Smoke the API**

Run: `uv run python -c "from fastapi.testclient import TestClient; from server.app import app, _index; c=TestClient(app); pid=next(iter(_index()['parcels'])); a=c.get(f'/api/analysis/{pid}').json(); s=a['scenarios'][0]; print(pid, s['typology_id'], s['metrics']['revenue.public_horizon'], a['tension_flags'])"`
Expected: a revenue metric with `provenance: placeholder` (millage still a stand-in) and a range, and a (possibly empty) list of tension flags.

- [ ] **Step 3: Report**

State plainly: which tests pass, the two pre-existing failures, the comps coverage numbers from the build log, and that every tax figure is a labeled placeholder pending human review.
