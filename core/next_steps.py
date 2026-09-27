"""What a CDC can do next on one lot, and who to contact.

A presentation layer over evidence the engine already has: ownership from the
city inventory, zoning results and their failed checks, site flags, and the
open questions in core/inquiries.py. It decides which steps apply; every word,
contact and question comes from next_steps.yaml.

Each step carries numbered facts. Those are the only things an outreach draft
may state (server/draft.py), and they are what the template letter lists.
Nothing here says what to build: a step is about finding out or asking.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from core.config import FEMA_FLOOD_FIELD, FEMA_FLOOD_KEY, Config, Contact
from core.engine import Analysis
from core.inquiries import _fill
from core.inquiries import build as build_inquiries

StepKind = Literal["acquire", "zoning", "confirm", "site_check", "neighborhood"]
# Zoning roles that mean "possible, but not over the counter".
_ASK_ROLES = ("staff_review", "discretionary", "variance")


class Fact(BaseModel):
    id: str
    text: str


class Step(BaseModel):
    id: StepKind
    title: str
    why: str
    facts: list[Fact] = []
    questions: list[str] = []
    contact: Contact | None = None
    # Deterministic letter built from the facts and questions. The fallback for
    # an AI draft, and usable on its own.
    letter: str
    # True when the answer can stop the project rather than shape it.
    blocking: bool = False
    note: str | None = None


def lot_fields(a: Analysis) -> dict[str, object]:
    p = a.parcel
    return {
        "address": p.get("address") or f"parcel {p.get('id')}",
        "parcel_id": p.get("id") or "",
        "neighborhood": p.get("neighborhood") or "this neighborhood",
        "district": p.get("zoning") or "an unmapped district",
        "lot_area_sf": f"{round(float(p.get('lot_area_sf') or 0)):,}",
        "inventory_type": p.get("public_inventory_type") or "unknown",
        "status": p.get("public_status") or "unknown",
    }


def _num(x: float) -> str:
    return f"{x:,.0f}" if float(x).is_integer() else f"{x:,.2f}".rstrip("0").rstrip(".")


def letter(cfg: Config, fields: dict[str, object], facts: list[Fact], questions: list[str]) -> str:
    d = cfg.next_steps.draft
    parts = [d.greeting, _fill(d.intro, fields)]
    if facts:
        parts.append(d.facts_lead + "\n" + "\n".join(f"- {f.text}" for f in facts))
    if questions:
        parts.append(d.questions_lead + "\n" + "\n".join(f"{i}. {q}" for i, q in enumerate(questions, 1)))
    parts += [d.closing, d.sign_off]
    return "\n\n".join(parts)


def build(cfg: Config, a: Analysis) -> list[Step]:
    ns = cfg.next_steps
    f = lot_fields(a)
    p = a.parcel
    labels = {t.id: t.label for t in cfg.typologies}
    steps: list[Step] = []

    def step(kind: StepKind, title: str, why: str, facts: list[str], questions: list[str], contact: str,
             **kw: object) -> Step:
        fs = [Fact(id=f"f{i}", text=t) for i, t in enumerate(facts, 1)]
        qs = [_fill(q, f) for q in questions]
        return Step(id=kind, title=title, why=_fill(why, f), facts=fs, questions=qs,
                    contact=ns.contacts[contact], letter=letter(cfg, f, fs, qs), **kw)

    inquiries = {i.kind: i for i in build_inquiries(cfg, a)}

    # 1. A publicly held lot: availability first, because no answer below matters
    #    if it cannot be acquired.
    if p.get("public"):
        acq = ns.acquire
        contact = acq.by_inventory_type.get(str(p.get("public_inventory_type")), acq.default_contact)
        facts = [f"City inventory type: {f['inventory_type']}; status: {f['status']}.",
                 f"Lot area on the county assessment: {f['lot_area_sf']} sq ft."]
        questions = []
        if (i := inquiries.get("public_parcel")) is not None:
            questions.append(i.question)
            questions.append(_fill(acq.ask_for_question, {"ask_for": i.ask_for[:1].lower() + i.ask_for[1:]}))
        not_for_sale = p.get("public_status") in acq.not_for_sale_statuses
        steps.append(step("acquire", acq.title, acq.why, facts, questions, contact, blocking=True,
                          note=_fill(acq.not_for_sale_note, f) if not_for_sale else None))

    # 2. Options that need a hearing or a variance: what fails, and where the code says so.
    ask = [s for s in a.scenarios if cfg.zoning.statuses[s.zoning.status].role in _ASK_ROLES]
    if ask:
        facts: list[str] = []
        for s in ask:
            cite = f" ({s.zoning.use_citation})" if s.zoning.use_citation else ""
            facts.append(f"{labels[s.typology_id]}: {s.zoning.status_label}{cite}.")
            for c in s.zoning.checks:
                if not c.passed:
                    where = f", {c.citation or c.code_section}" if (c.citation or c.code_section) else ""
                    facts.append(f"{labels[s.typology_id]} fails {c.label}: {_num(c.required)} {c.unit} "
                                 f"required, {_num(c.actual)} {c.unit} here{where}.")
        z = ns.zoning
        steps.append(step("zoning", z.title, z.why, facts, z.questions, z.contact))

    # 3. Zoning that no planner has confirmed: unreviewed districts, or rules in
    #    force only because AI extracted them.
    unreviewed = [s for s in a.scenarios if not s.zoning.reviewed]
    unchecked = [s for s in a.scenarios if s.zoning.reviewed and not s.zoning.human_reviewed]
    if unreviewed or unchecked:
        c = ns.confirm
        why = c.why_unreviewed if unreviewed else c.why_unchecked
        facts = [f"{labels[s.typology_id]}: {s.zoning.status_label}"
                 + (f" ({s.zoning.use_citation})" if s.zoning.use_citation else "")
                 + ("" if s.zoning.reviewed else ", no rule in force")
                 + ("" if not s.zoning.reviewed or s.zoning.human_reviewed else ", extracted by AI, not checked")
                 + "." for s in a.scenarios]
        steps.append(step("confirm", c.title, why, facts, c.questions, c.contact, blocking=bool(unreviewed)))

    # 4. Site conditions an engineer should look at before design money is spent.
    sc = ns.site_check
    flags = {h: bool(p.get(h)) for h in cfg.hazards}
    flags[FEMA_FLOOD_KEY] = bool(p.get(FEMA_FLOOD_FIELD))
    hit = [h for h, on in flags.items() if on and h in sc.hazards]
    if hit:
        hazard_labels = {h: spec["label"] for h, spec in cfg.hazards.items()}
        hazard_labels[FEMA_FLOOD_KEY] = sc.flood_label
        facts = [f"Flagged: {hazard_labels[h]}." for h in hit]
        questions = [q for h in hit for q in sc.hazards[h]]
        steps.append(step("site_check", sc.title, sc.why, facts, questions, sc.contact))

    # 5. Always: the neighborhood. Which RCO covers the lot is not in the data yet.
    nb = ns.neighborhood
    steps.append(step("neighborhood", nb.title, nb.why,
                      [f"Neighborhood: {f['neighborhood']}.", f"Zoning district: {f['district']}."],
                      nb.discussion_questions, nb.contact, note=_fill(nb.rco_placeholder, f)))
    return steps
