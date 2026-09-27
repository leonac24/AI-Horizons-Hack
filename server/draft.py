"""AI-drafted outreach for one next step: a short email the user edits and sends.

The model writes only body paragraphs, from the step's facts and questions.
Greeting, sign-off and subject come from config. A draft is kept only if every
paragraph that states something cites the facts it uses, every number is one
the step already contains, and any email address or link is one we supplied.
Otherwise the step's template letter is returned. Nothing is ever sent.
"""

from __future__ import annotations

import json
import logging
import re

from core.config import Config
from core.engine import Analysis
from core.inquiries import _fill
from core.next_steps import Step, lot_fields
from server.explain import NUM, allowed_numbers
from server.llm import LLMUnavailable, Provider

SYSTEM = """You draft a short, plain email from a Pittsburgh community development organization
to the contact named in "step". Use ONLY the facts in the input; do not add outside facts,
names, prices, dates, links or email addresses.
Rules:
- Write at most {max_paragraphs} body paragraphs. No greeting and no sign-off; those are added for you.
- A paragraph that states a fact about the lot must list the fact ids it uses in "fact_ids".
  A paragraph that only asks questions or says thank you may have an empty "fact_ids".
- Only use numbers that appear in the input. Ask the step's questions in your own words.
- Be polite and specific. Do not promise anything, and never say what will be built."""

SCHEMA = {
    "type": "object",
    "properties": {
        "paragraphs": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "fact_ids": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["text", "fact_ids"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["paragraphs"],
    "additionalProperties": False,
}

# Contact details a draft might invent. Each must already be in the input.
_CONTACTISH = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+|https?://\S+|www\.\S+", re.IGNORECASE)

log = logging.getLogger("lotline.draft")


def build_input(step: Step, fields: dict[str, object]) -> dict:
    c = step.contact
    return {
        "lot": {k: fields[k] for k in ("address", "parcel_id", "neighborhood", "district", "lot_area_sf")},
        "step": {"title": step.title, "why": step.why, "contact": c.label if c else None,
                 "facts": [f.model_dump() for f in step.facts], "questions": step.questions},
    }


def validate(payload: dict, out: object, max_paragraphs: int) -> list[str] | None:
    """Paragraph texts, or None if anything is off. Total: never raises."""
    if not isinstance(out, dict) or not isinstance(out.get("paragraphs"), list) or not out["paragraphs"]:
        return None
    fact_ids = {f["id"] for f in payload["step"]["facts"]}
    allowed = allowed_numbers(payload)
    raw = json.dumps(payload, ensure_ascii=False).lower()
    texts, cited = [], False
    for para in out["paragraphs"][:max_paragraphs]:
        if not isinstance(para, dict):
            return None
        text, ids = para.get("text"), para.get("fact_ids")
        if not isinstance(text, str) or not text.strip() or not isinstance(ids, list):
            return None
        if any(not isinstance(i, str) or i not in fact_ids for i in ids):
            return None
        cited = cited or bool(ids)
        for tok in NUM.findall(text):
            try:
                x = float(tok.replace(",", "").rstrip("."))
            except ValueError:
                return None
            if x not in allowed and round(x) not in allowed:
                return None
        if any(m.lower().rstrip(".,)") not in raw for m in _CONTACTISH.findall(text)):
            return None
        texts.append(text.strip())
    return texts if cited or not fact_ids else None


def draft(cfg: Config, provider: Provider, a: Analysis, step: Step) -> dict:
    d = cfg.next_steps.draft
    fields = lot_fields(a)
    subject = _fill(d.subject, {**fields, "title": step.title})
    to = step.contact.email if step.contact else None
    payload = build_input(step, fields)
    try:
        out = provider.complete_json(SYSTEM.replace("{max_paragraphs}", str(d.max_paragraphs)),
                                     json.dumps(payload, ensure_ascii=False), schema=SCHEMA,
                                     effort=cfg.app.explanation.effort, timeout_s=cfg.app.explanation.timeout_s,
                                     max_tokens=cfg.app.explanation.max_tokens)
        paragraphs = validate(payload, out, d.max_paragraphs)
        if paragraphs:
            body = "\n\n".join([d.greeting, *paragraphs, d.closing, d.sign_off])
            return {"source": provider.name, "subject": subject, "to": to, "body": body}
        reason = "model draft failed the fact check"
    except LLMUnavailable as e:
        reason = str(e)
    except Exception:
        log.exception("draft provider raised")
        reason = "provider error"
    return {"source": "template", "reason": reason, "subject": subject, "to": to, "body": step.letter}
