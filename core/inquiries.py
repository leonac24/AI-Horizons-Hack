"""Turn what we do not know about one parcel into what to go and find out.

Lotline is not allowed to say what to build. It is allowed to say what to go and
learn, because it is the only thing in the room that knows which unknowns are
still holding the answer up. That is what this module produces: for every gap
behind one parcel's evidence, the question to ask, who answers it, and what to
ask them for.

Nothing here weighs anything. Ordering a work plan by *decision leverage* — how
much settling a question would actually move the ranking — needs the user's
weights, so it happens in the browser (web/src/lib/leverage.ts). This module
builds the catalogue that ordering is then applied to.

The one ordering rule applied here is structural rather than normative: a
question whose answer can exclude an option outright sorts above one that can
only reorder, because no weighting can undo an exclusion. Cost and timing are
carried through untouched and never sorted on — see `CostRange` in
core/config.py for why they are allowed to exist at all.

Questions are found by following the dependency edges the engine recorded while
it did the arithmetic (`Metric.dependsOn`), so a question cannot drift away from
the number it is about. No metric id, resolver name or Pittsburgh fact is written
here; all of it comes from inquiries.yaml.
"""

from __future__ import annotations

from pydantic import BaseModel

from core.config import Config, InquiryRecord, InquiryTrigger, Provenance
from core.engine import Analysis

# An assumption is a question worth asking when its band is open, or when it was
# never sourced at all. A zero-width `assumption` is a declared modelling
# convention rather than an unknown — asking someone to "find out" the cost-burden
# threshold would be noise — so those are left out.
_OPEN_PROVENANCE: tuple[Provenance, ...] = ("placeholder",)

# Availability comes before legality, legality before anything measured: there is
# no point pricing a lot you cannot buy, or a use you will not be granted. Within
# a kind, questions holding up more numbers come first.
_KIND_ORDER: dict[InquiryTrigger, int] = {
    "public_parcel": 0, "zoning_use": 1, "zoning_dimensional": 2, "lot_shape": 3, "assumption": 4,
}


class Money(BaseModel):
    """An illustrative planning range. Always a placeholder, never an evidence
    metric, and never an input to any ordering."""

    low: float
    high: float
    unit: str
    provenance: Provenance = "placeholder"


class Inquiry(BaseModel):
    id: str
    kind: InquiryTrigger
    question: str
    why: str
    resolver: str
    resolver_label: str
    resolver_kind: str
    contact_hint: str | None = None
    ask_for: str
    effort: str
    effort_label: str
    effort_order: int
    contact_template: str
    cost: Money | None = None
    weeks: Money | None = None
    # Metric ids this question holds up, read off the engine's dependency edges.
    # The browser maps these to criteria to work out leverage.
    affects_metric_ids: list[str] = []
    # Can its answer exclude an option, rather than merely reorder the ranking?
    blocks_eligibility: bool = False
    citation: str | None = None
    quote: str | None = None
    sourceIds: list[str] = []
    # False when no record in inquiries.yaml matched and the card was built from
    # the assumption's own rationale. Shown as a weaker card, not hidden.
    matched: bool = True
    # The assumption key an answer would pin, when the answer is a number. Zoning
    # and availability questions are answered with a status, so they have none.
    assumption_key: str | None = None
    unit: str | None = None
    current_low: float | None = None
    current_high: float | None = None


class _Fill(dict):
    """Leaves an unknown placeholder visible instead of raising.

    Templates are config, so a typo in one must not turn into a 500. A stray
    `{foo}` comes out as `{foo}` and is obvious in review.
    """

    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def _fill(template: str, fields: dict[str, object]) -> str:
    try:
        return template.format_map(_Fill(fields))
    except (IndexError, ValueError):
        # Unbalanced or positional braces in config: show the template as written.
        return template


def _depends(analysis: Analysis) -> dict[str, list[str]]:
    """assumption key -> the metric ids resting on it, for this parcel."""
    out: dict[str, set[str]] = {}
    metrics = list(analysis.site_context)
    for s in analysis.scenarios:
        metrics.extend(s.metrics.values())
    for m in metrics:
        for key in m.dependsOn:
            out.setdefault(key, set()).add(m.id)
    return {k: sorted(v) for k, v in out.items()}


def build(cfg: Config, analysis: Analysis) -> list[Inquiry]:
    """The questions this parcel raises, most consequential kind first."""
    inq = cfg.inquiries
    depends = _depends(analysis)
    out: list[Inquiry] = []
    # Assumptions already spoken for by a zoning or availability question, so the
    # same gap is not also listed as a bare number to go and look up.
    claimed: set[str] = set()

    def make(iid: str, key: str, rec: InquiryRecord, fields: dict[str, object], *,
             matched: bool = True, citation: str | None = None, quote: str | None = None,
             assumption_key: str | None = None) -> Inquiry:
        resolver = inq.resolvers[rec.resolver]
        tier = inq.effort_tiers[rec.effort]
        pinned = assumption_key or rec.pins
        asm = cfg.assumptions.get(pinned) if pinned else None
        if pinned:
            claimed.add(pinned)
        # A question is answerable with a number only when it is *about* that
        # number. A zoning question may pin the same assumption to say which
        # metrics it holds up, but its answer is a status, not a value.
        numeric = assumption_key if (asm is not None and rec.trigger == "assumption") else None
        if asm is not None:
            # The pinned assumption's own numbers, so any record's text can quote
            # the band it is asking about. Explicit fields still win.
            fields = {"low": asm.low, "high": asm.high, "value": asm.value, "unit": asm.unit,
                      "rationale": asm.rationale.strip(), **fields}
        return Inquiry(
            id=iid,
            kind=rec.trigger,
            question=_fill(rec.question, fields),
            why=_fill(rec.why, fields),
            resolver=rec.resolver,
            resolver_label=resolver.label,
            resolver_kind=resolver.kind,
            contact_hint=resolver.contact_hint,
            ask_for=_fill(rec.ask_for, fields),
            effort=rec.effort,
            effort_label=tier.label,
            effort_order=tier.order,
            contact_template=_fill(rec.contact_template, fields),
            cost=Money(**rec.cost.model_dump()) if rec.cost else None,
            weeks=Money(**rec.weeks.model_dump()) if rec.weeks else None,
            affects_metric_ids=depends.get(pinned or "", []),
            blocks_eligibility=rec.blocks_eligibility,
            citation=citation,
            quote=quote,
            sourceIds=[s for s in [rec.source, asm.source if asm else None] if s],
            matched=matched,
            # Only a numeric assumption can be answered with a number. A zoning
            # question is answered with a status, which is a separate override, so
            # it carries no band for the user to replace.
            assumption_key=numeric,
            unit=asm.unit if numeric else None,
            current_low=asm.low if numeric else None,
            current_high=asm.high if numeric else None,
        )

    parcel = analysis.parcel
    base: dict[str, object] = {
        "parcel_id": parcel.get("id") or "",
        "address": parcel.get("address") or "this parcel",
        "district": parcel.get("zoning") or "an unmapped district",
        "neighborhood": parcel.get("neighborhood") or "this neighborhood",
        "lot_area_sf": round(float(parcel.get("lot_area_sf") or 0)),
    }

    # 1. Is the lot actually available? Ownership is not availability, and for a
    #    publicly held parcel this is the first real move — and an answer that can
    #    stop the project rather than reorder it.
    if parcel.get("public"):
        key, rec = inq.by_trigger("public_parcel")
        out.append(make(key, key, rec, base))

    # 2. Districts with no use rule in force yet. Everything about such a
    #    lot is provisional, so this is asked once per district, not per typology.
    if any(not s.zoning.reviewed for s in analysis.scenarios):
        key, rec = inq.by_trigger("zoning_use")
        unreviewed = sorted({s.zoning.district or "" for s in analysis.scenarios if not s.zoning.reviewed})
        forms = sorted({t.label for t in cfg.typologies
                        for s in analysis.scenarios
                        if s.typology_id == t.id and not s.zoning.reviewed})
        out.append(make(key, key, rec, {**base, "forms": ", ".join(forms),
                                        "districts": ", ".join(d for d in unreviewed if d)}))

    # 3. Dimensional rules this parcel fails. The engine has already turned these
    #    into a variance path; the question is what that path actually takes.
    seen_rules: set[str] = set()
    for s in analysis.scenarios:
        for check in s.zoning.checks:
            if check.passed or check.rule_id in seen_rules:
                continue
            seen_rules.add(check.rule_id)
            rec = inq.inquiries.get(check.rule_id)
            if rec is None or rec.trigger != "zoning_dimensional":
                continue
            out.append(make(check.rule_id, check.rule_id, rec, {
                **base, "rule_label": check.label, "required": check.required,
                "actual": check.actual, "rule_unit": check.unit,
            }, citation=check.citation, quote=check.quote))

    # 3b. A lot whose dimensions were never recorded. Its frontage and depth are
    #     drawn from area and a ratio, and every question about what fits here
    #     rests on that drawing.
    if analysis.lot_shape.provenance == "placeholder":
        found = next(((k, r) for k, r in inq.inquiries.items() if r.trigger == "lot_shape"), None)
        if found is not None:
            key, rec = found
            out.append(make(key, key, rec, {
                **base, "frontage": round(analysis.lot_shape.frontage_ft),
                "depth": round(analysis.lot_shape.depth_ft),
            }))

    # 4. Every open number the evidence rests on.
    for key in sorted(depends):
        if key in claimed:
            continue
        asm = cfg.assumptions.get(key)
        if asm is None:
            continue
        if not (asm.high > asm.low or asm.provenance in _OPEN_PROVENANCE):
            continue
        rec = inq.inquiries.get(key)
        matched = rec is not None and rec.trigger == "assumption"
        if not matched:
            rec = inq.generic
        out.append(make(key, key, rec, {**base, "label": key.replace("_", " ")},
                        matched=matched, assumption_key=key))

    # Exclusions first, then the questions holding up the most numbers, then the
    # cheapest kind of work. Leverage reorders this in the browser.
    out.sort(key=lambda i: (not i.blocks_eligibility, _KIND_ORDER[i.kind],
                            -len(i.affects_metric_ids), i.effort_order, i.id))
    return out
