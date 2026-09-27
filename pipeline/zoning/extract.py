"""Offline zoning-rule extraction from Title Nine text → rules_review.yaml.

    # 1. Save code text (eCode360 blocks scripts, so read it in a browser):
    #    one .txt per chapter in data/raw/zoning/, named by number, e.g. 911.txt
    # 2. Uses, per BASE district, from the Chapter 911 use table:
    #      uv run python -m pipeline.zoning.extract uses --only 911 \
    #        --keys R1D R1A R2 R3 RM H P
    # 3. Dimensions, per development SUBDISTRICT, from § 903.03:
    #      uv run python -m pipeline.zoning.extract dims --only 903 \
    #        --keys VL L M H VH

Use and dimension are extracted apart because Title Nine sets them apart: the
use table is keyed on the base district, § 903.03 on the subdistrict suffix.
A parcel zoned `R1D-H` needs one of each, so roughly thirty extractions cover
all fifty-four district codes in the city and no use rule is transcribed twice.

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
from server.llm import DEFAULT_MODEL, AnthropicProvider, LLMUnavailable

log = logging.getLogger("zoning")

# Roles a rule can be extracted *as*. `variance` and `unreviewed` are never
# extracted — the engine works them out from a failed dimensional check or from
# the absence of a reviewed rule — so offering them to the model would invite it
# to answer a question the code text cannot answer.
EXTRACTABLE_ROLES = ("permitted", "staff_review", "discretionary", "prohibited")


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


class UseRules(BaseModel):
    uses: dict[str, UseRule] = {}


class DimRules(BaseModel):
    dimensional: dict[str, DimRule] = {}


USES_SYSTEM = """You extract use permissions from the Pittsburgh Zoning Code text provided.
Use ONLY the provided text. The use table lists one column per base zoning district; read
down the column for the district you are asked about. If the cell is blank, the use is not
permitted — report it with the status given for that. If the district is not in the table,
omit the use entirely rather than guessing.
Every rule needs: code_section (e.g. "911.02"), a verbatim quote of at most 25 words copied
exactly from the text, and confidence 0-1."""

DIMS_SYSTEM = """You extract dimensional standards from the Pittsburgh Zoning Code text provided.
Use ONLY the provided text. You are asked about one development subdistrict (the suffix on a
zoning map code, e.g. the H in R1D-H). Report only rules stated for that subdistrict; omit any
rule the text does not state for it.
Every rule needs: code_section (e.g. "903.03"), a verbatim quote of at most 25 words copied
exactly from the text, and confidence 0-1."""


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip().lower()


def _rows(key: str, keys: list[str], value: dict) -> dict:
    """Structured-output schema for a list of rules keyed by an enum from zoning.yaml,
    so the model cannot invent a use, status or rule the app doesn't know about."""
    props = {key: {"type": "string", "enum": keys}, **value,
             "code_section": {"type": "string"}, "quote": {"type": "string"},
             "confidence": {"type": "number"}}
    return {"type": "array", "items": {"type": "object", "properties": props,
                                       "required": list(props), "additionalProperties": False}}


def _schema(group: str, rows: dict) -> dict:
    return {"type": "object", "properties": {group: rows}, "required": [group], "additionalProperties": False}


def _keyed(raw: dict, group: str, key: str) -> dict:
    return {group: {r.pop(key): r for r in raw.get(group, [])}}


def _drop_unquoted(group: dict, text: str, key: str) -> None:
    """A rule whose quote is not in the source text verbatim is not evidence."""
    haystack = _norm(text)
    for k in list(group):
        q = group[k].quote
        if len(q.split()) >= 25 or _norm(q) not in haystack:
            log.warning("%s %s: quote not found verbatim or too long -> dropped", key, k)
            del group[k]


def extract_uses(cfg: Config, provider: AnthropicProvider, district: str, text: str, model: str) -> UseRules:
    allowed = [i for i, s in cfg.zoning.statuses.items() if s.role in EXTRACTABLE_ROLES]
    use_keys = cfg.zoning.extraction_targets.use_keys
    prompt = json.dumps({
        "base_district": district,
        "use_keys": use_keys,
        "statuses": {i: cfg.zoning.statuses[i].label for i in allowed},
        "code_text": text,
    })
    schema = _schema("uses", _rows("use_key", list(use_keys), {"status": {"type": "string", "enum": allowed}}))
    # Long legal text and accuracy matters: high effort, streamed, generous output room.
    raw = provider.complete_json(USES_SYSTEM, prompt, schema=schema, model=model, effort="high", max_tokens=32000)
    rules = UseRules.model_validate(_keyed(raw, "uses", "use_key"))
    for k in list(rules.uses):
        if rules.uses[k].status not in allowed:
            log.warning("%s %s: status %r not declared in zoning.yaml -> dropped",
                        district, k, rules.uses[k].status)
            del rules.uses[k]
    _drop_unquoted(rules.uses, text, district)
    return rules


def extract_dims(cfg: Config, provider: AnthropicProvider, subdistrict: str, text: str, model: str) -> DimRules:
    t = cfg.zoning.extraction_targets.dimensional
    prompt = json.dumps({
        "subdistrict": subdistrict,
        "dimensional_rules": {k: f"{v.label} ({v.unit})" for k, v in t.items()},
        "code_text": text,
    })
    schema = _schema("dimensional", _rows("rule_id", list(t), {"value": {"type": "number"}}))
    raw = provider.complete_json(DIMS_SYSTEM, prompt, schema=schema, model=model, effort="high", max_tokens=32000)
    rules = DimRules.model_validate(_keyed(raw, "dimensional", "rule_id"))
    for k in list(rules.dimensional):
        if k not in t:
            log.warning("%s %s: not a declared dimensional rule -> dropped", subdistrict, k)
            del rules.dimensional[k]
    _drop_unquoted(rules.dimensional, text, subdistrict)
    return rules


def _code_text(cfg: Config, only: list[str] | None) -> str:
    text_dir = ROOT / cfg.zoning.code.raw_text_dir
    files = sorted(Path(text_dir).glob("*.txt")) if text_dir.exists() else []
    if only:
        files = [f for f in files if f.stem in only]
    if not files:
        raise SystemExit(f"No code text in {text_dir}"
                         f"{' matching ' + ', '.join(only) if only else ''}."
                         " Save Title Nine chapters there first (see docstring).")
    log.info("code text: %s", ", ".join(f.stem for f in files))
    return "\n\n".join(f"[§ {f.stem}]\n{f.read_text(encoding='utf-8')}" for f in files)


def _default_districts(cfg: Config, limit: int) -> list[str]:
    """Base districts holding the most vacant parcels, worst-covered first."""
    prio = json.loads((ROOT / cfg.zoning.priority_file).read_text(encoding="utf-8"))
    seen: list[str] = []
    for row in prio:
        base, _ = cfg.zoning.district_code.split(row["district"])
        if base and base != "(none)" and base not in seen:
            seen.append(base)
    return seen[:limit]


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("what", choices=["uses", "dims"], help="uses = per base district; dims = per subdistrict")
    ap.add_argument("--keys", nargs="*", help="districts (uses) or suffixes (dims); default: busiest districts / all suffixes")
    ap.add_argument("--only", nargs="*", help="only these chapter files, e.g. --only 911")
    ap.add_argument("--limit", type=int, default=10)
    ap.add_argument("--retries", type=int, default=4, help="retries per key on 429/503/529")
    ap.add_argument("--backoff", type=int, default=15, help="first retry wait in seconds (doubles)")
    args = ap.parse_args()

    cfg = load_config()
    text = _code_text(cfg, args.only)
    section = "districts" if args.what == "uses" else "subdistricts"
    group = "uses" if args.what == "uses" else "dimensional"
    keys = args.keys or (_default_districts(cfg, args.limit) if args.what == "uses"
                         else list(cfg.zoning.district_code.subdistrict_suffixes))

    try:
        provider = AnthropicProvider()
    except LLMUnavailable as e:
        raise SystemExit(f"LLM unavailable: {e}") from e
    model = os.environ.get("ZONING_EXTRACT_MODEL", DEFAULT_MODEL)

    rules_path = ROOT / cfg.zoning.rules_file
    raw_rules = rules_path.read_text(encoding="utf-8")
    # safe_dump drops comments; keep the file's explanatory header.
    header = "".join(ln for ln in raw_rules.splitlines(keepends=True) if ln.startswith("#"))
    doc = yaml.safe_load(raw_rules) or {}
    doc.setdefault("districts", {})
    doc.setdefault("subdistricts", {})
    doc.setdefault("citywide", {})  # hand-verified city-wide uses; never written here
    store = doc[section] or {}

    def extract(key: str) -> dict:
        return (extract_uses(cfg, provider, key, text, model).uses if args.what == "uses"
                else extract_dims(cfg, provider, key, text, model).dimensional)

    for key in keys:
        got = None
        for attempt in range(args.retries + 1):
            try:
                got = extract(key)
                break
            except LLMUnavailable as e:
                transient = any(code in str(e) for code in ("429", "503", "529"))
                if not transient or attempt == args.retries:
                    log.error("%s: extraction failed: %s", key, str(e)[:200])
                    break
                wait = args.backoff * (2 ** attempt)
                log.warning("%s: provider busy or rate-limited, retrying in %ds", key, wait)
                time.sleep(wait)
            except ValidationError as e:
                log.error("%s: extraction failed: %s", key, e)
                break
        if got is None:
            continue
        cur = store.setdefault(key, {})
        stamp = {"extracted_by": model, "retrieved": str(datetime.now(UTC).date()), "reviewed": False}
        for k, r in got.items():
            if (cur.get(group) or {}).get(k, {}).get("reviewed"):
                continue  # never overwrite a human-reviewed rule
            cur.setdefault(group, {})[k] = {**r.model_dump(), **stamp}
        log.info("%s: %d %s rules", key, len(got), group)
        # Save after every key so a later failure never loses earlier work.
        doc[section] = store
        rules_path.write_text(header + "\n" + yaml.safe_dump(doc, sort_keys=False, allow_unicode=True),
                              encoding="utf-8")
    log.info("wrote %s", rules_path)


if __name__ == "__main__":
    main()
