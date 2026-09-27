"""Offline zoning-rule extraction from Title Nine text → rules_review.yaml.

    # 1. Save code text (eCode360 blocks scripts): one .txt per section in
    #    data/raw/zoning/, named by section number, e.g. 911.02.txt, 903.03.txt
    # 2. uv run python -m pipeline.zoning.extract [--districts R1D-H RM-M ...]

Every rule the model returns must quote the source text verbatim (< 25 words);
rules whose quote is not found in the supplied text are dropped. Output merges
into rules_review.yaml with `reviewed: false` — a teammate reviews each rule and
flips it to true. Existing reviewed rules are never overwritten.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, ValidationError

from core.config import ROOT, Config, load_config
from server.llm import DEFAULT_MODEL, AnthropicProvider, LLMUnavailable

log = logging.getLogger("zoning")


class UseRule(BaseModel):
    status: Literal["by_right", "special_exception", "conditional_use", "not_permitted"]
    code_section: str
    quote: str
    confidence: float = Field(ge=0, le=1)


class DimRule(BaseModel):
    value: float
    code_section: str
    quote: str
    confidence: float = Field(ge=0, le=1)


class DistrictRules(BaseModel):
    uses: dict[str, UseRule] = {}
    dimensional: dict[str, DimRule] = {}


SYSTEM = """You extract zoning rules from the Pittsburgh Zoning Code text provided.
Use ONLY the provided text. If a rule is not stated for the district, omit it.
Every rule needs: code_section (e.g. "911.02"), a verbatim quote of at most 25 words
copied exactly from the text, and confidence 0-1."""


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip().lower()


STATUSES = ["by_right", "special_exception", "conditional_use", "not_permitted"]


def _schema(cfg: Config) -> dict:
    """Structured-output schema. Keys are enums from zoning.yaml, so the model
    cannot invent a use or rule the app doesn't know about."""
    t = cfg.zoning.extraction_targets

    def rows(key: str, keys: list[str], value: dict) -> dict:
        props = {key: {"type": "string", "enum": keys}, **value,
                 "code_section": {"type": "string"}, "quote": {"type": "string"},
                 "confidence": {"type": "number"}}
        return {"type": "array", "items": {"type": "object", "properties": props,
                                           "required": list(props), "additionalProperties": False}}

    return {"type": "object",
            "properties": {"uses": rows("use_key", list(t.use_keys), {"status": {"type": "string", "enum": STATUSES}}),
                           "dimensional": rows("rule_id", list(t.dimensional), {"value": {"type": "number"}})},
            "required": ["uses", "dimensional"], "additionalProperties": False}


def extract_district(cfg: Config, provider: AnthropicProvider, district: str, text: str, model: str) -> DistrictRules:
    t = cfg.zoning.extraction_targets
    prompt = json.dumps({
        "district": district,
        "use_keys": t.use_keys,
        "dimensional_rules": {k: f"{v.label} ({v.unit})" for k, v in t.dimensional.items()},
        "code_text": text,
    })
    # Long legal text and accuracy matters: high effort, streamed, generous output room.
    raw = provider.complete_json(SYSTEM, prompt, schema=_schema(cfg), model=model, effort="high",
                                 max_tokens=32000)
    rules = DistrictRules.model_validate({
        "uses": {r.pop("use_key"): r for r in raw.get("uses", [])},
        "dimensional": {r.pop("rule_id"): r for r in raw.get("dimensional", [])},
    })
    haystack = _norm(text)
    for group in (rules.uses, rules.dimensional):
        for k in list(group):
            q = group[k].quote
            if len(q.split()) >= 25 or _norm(q) not in haystack:
                log.warning("%s %s: quote not found verbatim or too long -> dropped", district, k)
                del group[k]
    return rules


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--districts", nargs="*", help="default: districts by vacant-parcel count")
    ap.add_argument("--limit", type=int, default=10)
    args = ap.parse_args()

    cfg = load_config()
    text_dir = ROOT / cfg.zoning.code.raw_text_dir
    files = sorted(Path(text_dir).glob("*.txt")) if text_dir.exists() else []
    if not files:
        raise SystemExit(f"No code text in {text_dir}. Save Title Nine sections there first (see docstring).")
    text = "\n\n".join(f"[§ {f.stem}]\n{f.read_text(encoding='utf-8')}" for f in files)

    districts = args.districts
    if not districts:
        prio = json.loads((ROOT / cfg.zoning.priority_file).read_text(encoding="utf-8"))
        districts = [d["district"] for d in prio if d["district"] != "(none)"][: args.limit]

    try:
        provider = AnthropicProvider()
    except LLMUnavailable as e:
        raise SystemExit(f"LLM unavailable: {e}") from e
    model = os.environ.get("ZONING_EXTRACT_MODEL", DEFAULT_MODEL)

    rules_path = ROOT / cfg.zoning.rules_file
    doc = yaml.safe_load(rules_path.read_text(encoding="utf-8")) or {}
    all_rules = doc.get("districts") or {}
    for d in districts:
        try:
            got = extract_district(cfg, provider, d, text, model)
        except (LLMUnavailable, ValidationError) as e:
            log.error("%s: extraction failed: %s", d, e)
            continue
        cur = all_rules.setdefault(d, {"uses": {}, "dimensional": {}})
        stamp = {"extracted_by": model, "retrieved": str(datetime.now(UTC).date()), "reviewed": False}
        for group, new in (("uses", got.uses), ("dimensional", got.dimensional)):
            for k, r in new.items():
                if (cur.get(group) or {}).get(k, {}).get("reviewed"):
                    continue  # never overwrite a human-reviewed rule
                cur.setdefault(group, {})[k] = {**r.model_dump(), **stamp}
        log.info("%s: %d use rules, %d dimensional rules", d, len(got.uses), len(got.dimensional))
    doc["districts"] = all_rules
    rules_path.write_text(yaml.safe_dump(doc, sort_keys=False, allow_unicode=True), encoding="utf-8")


if __name__ == "__main__":
    main()
