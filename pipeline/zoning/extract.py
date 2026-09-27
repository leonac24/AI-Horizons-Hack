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
import time
from datetime import UTC, datetime
from pathlib import Path

import yaml
from pydantic import BaseModel, Field, ValidationError

from core.config import ROOT, Config, load_config
from server.llm import GeminiProvider, LLMUnavailable

log = logging.getLogger("zoning")


# Roles the engine derives itself; text never states them directly.
_DERIVED_ROLES = {"variance", "unreviewed"}


def extractable_statuses(cfg: Config) -> list[str]:
    return [k for k, s in cfg.zoning.statuses.items() if s.role not in _DERIVED_ROLES]


class UseRule(BaseModel):
    status: str
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
copied exactly from the text, and confidence 0-1. Return JSON only."""


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip().lower()


def extract_district(cfg: Config, provider: GeminiProvider, district: str, text: str, model: str) -> DistrictRules:
    t = cfg.zoning.extraction_targets
    statuses = extractable_statuses(cfg)
    prompt = json.dumps({
        "district": district,
        "use_keys": t.use_keys,
        "dimensional_rules": {k: f"{v.label} ({v.unit})" for k, v in t.dimensional.items()},
        "statuses": {k: cfg.zoning.statuses[k].label for k in statuses},
        "output_shape": {"uses": {"<use_key>": {"status": "...", "code_section": "...", "quote": "...", "confidence": 0.0}},
                         "dimensional": {"<rule_id>": {"value": 0, "code_section": "...", "quote": "...", "confidence": 0.0}}},
        "code_text": text,
    })
    raw = provider.complete_json(SYSTEM, prompt, model=model)
    rules = DistrictRules.model_validate(raw)
    haystack = _norm(text)
    for k in list(rules.uses):
        if rules.uses[k].status not in statuses:
            log.warning("%s %s: status %r not in zoning.yaml -> dropped", district, k, rules.uses[k].status)
            del rules.uses[k]
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
    ap.add_argument("--retries", type=int, default=4, help="retries per district on 429/503")
    ap.add_argument("--backoff", type=int, default=15, help="first retry wait in seconds (doubles)")
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
        provider = GeminiProvider()
    except LLMUnavailable as e:
        raise SystemExit(f"LLM unavailable: {e}") from e
    model = os.environ.get("ZONING_EXTRACT_MODEL", "gemini-3.8-flash")

    rules_path = ROOT / cfg.zoning.rules_file
    raw_rules = rules_path.read_text(encoding="utf-8")
    header = "".join(ln for ln in raw_rules.splitlines(keepends=True)[:40] if ln.startswith("#"))
    if header:
        header += "\n"
    doc = yaml.safe_load(raw_rules) or {}
    all_rules = doc.get("districts") or {}
    for d in districts:
        got = None
        for attempt in range(args.retries + 1):
            try:
                got = extract_district(cfg, provider, d, text, model)
                break
            except LLMUnavailable as e:
                transient = any(code in str(e) for code in ("429", "503"))
                if not transient or attempt == args.retries:
                    log.error("%s: extraction failed: %s", d, str(e)[:200])
                    break
                wait = args.backoff * (2 ** attempt)
                log.warning("%s: provider busy or rate-limited, retrying in %ds", d, wait)
                time.sleep(wait)
            except ValidationError as e:
                log.error("%s: extraction failed: %s", d, e)
                break
        if got is None:
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
        # Save after every district so a later failure never loses earlier work,
        # and keep the file's explanatory comment header (safe_dump drops comments).
        rules_path.write_text(header + yaml.safe_dump(doc, sort_keys=False, allow_unicode=True), encoding="utf-8")


if __name__ == "__main__":
    main()
