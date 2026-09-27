"""Evaluate zoning rules for a (district, typology, lot) combination.

Only rules in force produce a definite answer (see in_force: every extracted
rule, or only human-reviewed ones when zoning.yaml sets require_human_review).
Anything else — district missing, or no rule for the use — returns whichever
status zoning.yaml gives the `unreviewed` role.

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


class Setback(BaseModel):
    rule_id: str
    label: str
    value_ft: float
    citation: str | None
    quote: str | None


class ZoningResult(BaseModel):
    district: str | None
    status: str
    status_label: str
    # True when a rule in force answered; `human_reviewed` says whether a person
    # checked it, so the UI never presents an AI extraction as reviewed.
    reviewed: bool
    human_reviewed: bool = False
    use_citation: str | None = None
    use_quote: str | None = None
    checks: list[Check] = []
    max_units_by_rule: int | None = None
    # Reviewed setbacks for this district, keyed by rule id. Not checked here —
    # the engine has no building positions — but the 3D view draws and checks them.
    setbacks: dict[str, Setback] = {}
    note: str | None = None
    # A prohibited use is a hard requirement, not a criterion. Scenarios flagged
    # here are excluded from the ranking rather than scored, so weight on other
    # criteria can never make an illegal scenario come out on top.
    disqualified: bool = False
    disqualified_reason: str | None = None


@lru_cache(maxsize=4)
def _load_rules(path: str, mtime: float) -> dict:
    doc = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    return {"districts": doc.get("districts") or {}, "subdistricts": doc.get("subdistricts") or {},
            "citywide": doc.get("citywide") or {}}


def load_rules(cfg: Config) -> dict:
    p = ROOT / cfg.zoning.rules_file
    if not p.exists():
        return {"districts": {}, "subdistricts": {}, "citywide": {}}
    return _load_rules(str(p), p.stat().st_mtime)


def cite(cfg: Config, section: str | None) -> str | None:
    return cfg.zoning.code.citation_format.format(section=section) if section else None


def dimensional_rules(cfg: Config, rules: dict, district: str | None) -> dict:
    """The size rules that apply to a map code, reviewed or not.

    § 903.03 mostly varies by suffix alone, but some families differ within one
    suffix (RM-H is taller than R1D-H), so a family-specific entry (`RM-H`)
    overrides the generic suffix entry (`H`) rule by rule. A code with no suffix
    (H, P) states its own size rules, so they sit on the district itself."""
    base, sub = cfg.zoning.district_code.split(district)
    if not sub:
        return ((rules.get("districts") or {}).get(base or "") or {}).get("dimensional") or {}
    subs = rules.get("subdistricts") or {}
    return {**((subs.get(sub) or {}).get("dimensional") or {}),
            **((subs.get(f"{base}-{sub}") or {}).get("dimensional") or {})}


def in_force(cfg: Config, rule: dict | None) -> bool:
    """Whether a rule may decide an answer."""
    return bool(rule) and (bool(rule.get("reviewed")) or not cfg.zoning.require_human_review)


def covered_bases(cfg: Config, rules: dict, *, human_only: bool = False) -> set[str]:
    """Base districts with at least one use rule in force (or human-reviewed).
    City-wide uses are not counted: they settle one use everywhere, not one
    district's table."""
    ok = (lambda u: bool(u.get("reviewed"))) if human_only else (lambda u: in_force(cfg, u))
    return {b for b, r in (rules.get("districts") or {}).items()
            if any(ok(u) for u in (r.get("uses") or {}).values())}


def buildable_margins(cfg: Config, rules: dict, district: str | None) -> dict[str, float]:
    """Setbacks in force for a district as margins in feet: front, rear, left,
    right. Empty when no setback rule is in force. Side setbacks apply to both
    sides; where the code gives a different "other side" value it is used on
    the right. Exterior (street-side) yards apply only on corner lots, which we
    cannot identify, so they are not used here."""
    d = dimensional_rules(cfg, rules, district)
    def v(key: str) -> float | None:
        r = d.get(key)
        return float(r["value"]) if in_force(cfg, r) and r.get("value") is not None else None
    front, rear, side, other = (v("front_setback_ft"), v("rear_setback_ft"),
                                v("interior_side_setback_ft"), v("interior_side_other_ft"))
    if front is None and rear is None and side is None:
        return {}
    return {"front": front or 0.0, "rear": rear or 0.0, "left": side or 0.0,
            "right": other if other is not None else (side or 0.0)}


def evaluate(cfg: Config, rules: dict, district: str | None, typ: Typology, lot_area_sf: float | None,
             units: int, frontage_ft: float | None = None) -> ZoningResult:
    """`frontage_ft` is the lot width when it is OBSERVED; pass None when it is a
    placeholder, so width-conditional rules stay unresolved instead of guessed."""
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

    # Use comes from the base district, size and height from the development
    # subdistrict; `R1D-H` asks both (see dimensional_rules). A district with no
    # subdistrict (H, P, LNC) reads any size rules it states from itself.
    base_code, _ = cfg.zoning.district_code.split(district)
    d = (rules.get("districts") or {}).get(base_code or "")
    dims = {"dimensional": dimensional_rules(cfg, rules, district)}

    # A few uses are governed city-wide rather than by a column in the district
    # use table — Chapter 912 accessory uses are the case here. They are answered
    # before the district is consulted, because the table has no row for them at
    # all, and a missing row is not the same thing as a blank cell. (§ 911.01
    # says a blank cell means not permitted; it says nothing about a use the
    # table never lists.) As everywhere else, only a rule in force decides.
    use = ((rules.get("citywide") or {}).get("uses") or {}).get(typ.use_key)
    if not in_force(cfg, use):
        if not district or not d:
            return result(unreviewed, reviewed=False,
                          note="No zoning rules have been extracted for this district yet.")
        use = (d.get("uses") or {}).get(typ.use_key)
    if not in_force(cfg, use):
        return result(unreviewed, reviewed=False,
                      note=("Use rule for this housing type is not reviewed yet." if use
                            else "No use rule has been extracted for this housing type here."))
    status = use["status"]
    cond = use.get("when_frontage_at_most")
    if cond:
        if frontage_ft is None:
            return result(unreviewed, reviewed=False,
                          note=f"Depends on lot width (≤ {cond['ft']:g} ft vs wider, "
                               f"{cite(cfg, use.get('code_section'))}); this lot's width is not observed.")
        if frontage_ft <= float(cond["ft"]):
            status = cond["status"]
    base = {"reviewed": True, "human_reviewed": bool(use.get("reviewed")),
            "use_citation": cite(cfg, use.get("code_section")),
            "use_quote": use.get("quote"), "note": use.get("note")}
    if cfg.zoning.is_disqualifying(status):
        return result(status, **base)

    checks: list[Check] = []
    setbacks: dict[str, Setback] = {}
    max_units: int | None = None
    lot = float(lot_area_sf or 0)
    stories = typ.stories
    # The code states height in feet; a typology is described in stories.
    height_ft = typ.stories * typ.floor_height_ft
    for rule_id, target in cfg.zoning.extraction_targets.dimensional.items():
        rule = (dims.get("dimensional") or {}).get(rule_id)
        if not in_force(cfg, rule) or rule.get("value") is None:
            continue
        req = float(rule["value"])
        if target.check == "setback":
            setbacks[rule_id] = Setback(rule_id=rule_id, label=target.label, value_ft=req,
                                        citation=cite(cfg, rule.get("code_section")), quote=rule.get("quote"))
            continue
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
    return result(status, checks=checks, setbacks=setbacks, max_units_by_rule=max_units, **base)
