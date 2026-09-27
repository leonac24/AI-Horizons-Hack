"""Evaluate reviewed zoning rules for a (district, typology, lot) combination.

Only rules with `reviewed: true` produce a definite answer. Anything else —
district missing, or the use rule not yet reviewed — returns whichever status
zoning.yaml gives the `unreviewed` role.

Status ids are never written here. Code asks zoning.yaml for the status playing
a role, so renaming a status in config cannot silently change behaviour.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel

from core.config import ROOT, Config, Typology


class Check(BaseModel):
    rule_id: str
    label: str
    required: float
    actual: float
    unit: str
    passed: bool
    code_section: str | None
    citation: str | None
    quote: str | None


class ZoningResult(BaseModel):
    district: str | None
    status: str
    status_label: str
    reviewed: bool
    use_citation: str | None = None
    use_quote: str | None = None
    checks: list[Check] = []
    max_units_by_rule: int | None = None
    note: str | None = None
    # A prohibited use is a hard requirement, not a criterion. Scenarios flagged
    # here are excluded from the ranking rather than scored, so weight on other
    # criteria can never make an illegal scenario come out on top.
    disqualified: bool = False
    disqualified_reason: str | None = None


@lru_cache(maxsize=4)
def _load_rules(path: str, mtime: float) -> dict:
    return (yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}).get("districts") or {}


def load_rules(cfg: Config) -> dict:
    p = ROOT / cfg.zoning.rules_file
    if not p.exists():
        return {}
    return _load_rules(str(p), p.stat().st_mtime)


def cite(cfg: Config, section: str | None) -> str | None:
    return cfg.zoning.code.citation_format.format(section=section) if section else None


def evaluate(cfg: Config, rules: dict, district: str | None, typ: Typology, lot_area_sf: float | None,
             units: int) -> ZoningResult:
    labels = {k: v.label for k, v in cfg.zoning.statuses.items()}
    unreviewed = cfg.zoning.status_id("unreviewed")
    variance = cfg.zoning.status_id("variance")

    def result(status: str, **kw) -> ZoningResult:
        if status not in labels:
            raise KeyError(f"rules file used status {status!r}, not declared in zoning.yaml statuses")
        return ZoningResult(district=district, status=status, status_label=labels[status],
                            disqualified=cfg.zoning.is_disqualifying(status),
                            disqualified_reason=labels[status] if cfg.zoning.is_disqualifying(status) else None,
                            **kw)

    d = rules.get(district or "")
    if not district or not d:
        return result(unreviewed, reviewed=False,
                      note="This district's rules have not been extracted and reviewed yet.")
    use = (d.get("uses") or {}).get(typ.use_key)
    if not use or not use.get("reviewed"):
        return result(unreviewed, reviewed=False,
                      note="Use rule for this housing type is not reviewed yet.")
    status = use["status"]
    base = {"reviewed": True, "use_citation": cite(cfg, use.get("code_section")), "use_quote": use.get("quote")}
    if cfg.zoning.is_disqualifying(status):
        return result(status, **base)

    checks: list[Check] = []
    max_units: int | None = None
    lot = float(lot_area_sf or 0)
    stories = typ.stories
    # The code states height in feet; a typology is described in stories.
    height_ft = typ.stories * typ.floor_height_ft
    for rule_id, target in cfg.zoning.extraction_targets.dimensional.items():
        rule = (d.get("dimensional") or {}).get(rule_id)
        if not rule or not rule.get("reviewed") or rule.get("value") is None:
            continue
        req = float(rule["value"])
        match target.check:
            case "lot_area_at_least":
                actual, ok = lot, lot >= req
            case "lot_area_per_unit_at_least":
                actual, ok = lot / max(units, 1), lot / max(units, 1) >= req
                max_units = int(lot // req) if req > 0 else None
            case "height_at_most":
                actual, ok = height_ft, height_ft <= req
            case "stories_at_most":
                actual, ok = stories, stories <= req
        checks.append(Check(rule_id=rule_id, label=target.label, required=req, actual=round(actual, 1),
                            unit=target.unit, passed=ok, code_section=rule.get("code_section"),
                            citation=cite(cfg, rule.get("code_section")), quote=rule.get("quote")))
    if any(not c.passed for c in checks):
        status = variance
    return result(status, checks=checks, max_units_by_rule=max_units, **base)
