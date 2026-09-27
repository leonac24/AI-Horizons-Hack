"""Expand reviewed-or-not zoning facts onto every mapped district.

    uv run python -m pipeline.zoning.build_rules          # verify quotes, write rules_review.yaml + REVIEW.md
    uv run python -m pipeline.zoning.build_rules --apply  # first copy ticks from REVIEW.md into facts.yaml

facts.yaml holds one entry per statement in the code, each with verbatim quotes
from data/sources/zoning/. A person reviews facts (not districts) in REVIEW.md.
Every rule written to rules_review.yaml inherits its fact's `reviewed` flag, and
the engine only acts on reviewed rules.
"""

from __future__ import annotations

import argparse
import getpass
import json
import re
import subprocess
from datetime import UTC, datetime

import yaml

from core.config import ROOT, load_config

FACTS = ROOT / "pipeline" / "zoning" / "facts.yaml"
REVIEW = ROOT / "pipeline" / "zoning" / "REVIEW.md"
SNAPSHOTS = ROOT / "data" / "sources" / "zoning"
MAX_QUOTE_WORDS = 25
_WS = re.compile(r"\s+")


def _norm(s: str) -> str:
    return _WS.sub(" ", s).strip()


class FactError(ValueError):
    pass


def verify(facts: dict) -> None:
    """Every quote must be < 25 words and appear verbatim in its snapshot file."""
    errors = []
    for f in facts["use_facts"] + facts["dimensional_facts"]:
        path = SNAPSHOTS / f["file"]
        if not path.exists():
            errors.append(f"{f['id']}: snapshot {f['file']} missing")
            continue
        text = _norm(path.read_text(encoding="utf-8"))
        for q in f["quotes"]:
            if len(q.split()) >= MAX_QUOTE_WORDS:
                errors.append(f"{f['id']}: quote has {len(q.split())} words (limit {MAX_QUOTE_WORDS - 1})")
            if _norm(q) not in text:
                errors.append(f"{f['id']}: quote not found verbatim in {f['file']}: {q!r}")
    if errors:
        raise FactError("zoning facts failed verification:\n  - " + "\n  - ".join(errors))


def _split(district: str, families: list[str]) -> tuple[str | None, str | None]:
    head, _, tail = district.partition("-")
    return (head, tail or None) if head in families else (None, None)


def _rule(fact: dict, **extra) -> dict:
    return {
        **extra,
        "code_section": fact["section"],
        "quote": fact["quotes"][0],
        "confidence": fact["confidence"],
        "extracted_by": "claude-code",
        "fact_id": fact["id"],
        "reviewed": bool(fact.get("reviewed")),
        **({"reviewed_by": fact["reviewed_by"], "reviewed_on": fact["reviewed_on"]} if fact.get("reviewed") else {}),
    }


def expand(facts: dict, districts: list[str]) -> dict:
    letters = facts["status_letters"]
    families = facts["families"]
    specials = facts["special_districts"]
    width_rules = {f["use_key"]: f for f in facts["use_facts"] if f.get("frontage_rule")}
    out: dict = {}
    for d in districts:
        fam, density = _split(d, families)
        column = fam or (d if d in specials else None)
        if column is None:
            continue
        uses: dict = {}
        for f in facts["use_facts"]:
            if "cells" not in f or column not in f["cells"]:
                continue
            cell = f["cells"][column]
            if cell == "P/S":
                w = width_rules.get(f["use_key"])
                if not w or w["frontage_rule"]["family"] != column:
                    continue
                fr = w["frontage_rule"]
                # Both facts must be reviewed for the split to be trusted.
                both = bool(f.get("reviewed")) and bool(w.get("reviewed"))
                rule = _rule(w, status=fr["otherwise"],
                             when_frontage_at_most={"ft": fr["at_most_ft"], "status": fr["status"]})
                rule["reviewed"] = both
                uses[f["use_key"]] = rule
            else:
                uses[f["use_key"]] = _rule(f, status=letters[cell])
        dimensional: dict = {}
        for f in facts["dimensional_facts"]:
            a = f["applies"]
            hit = (d in a.get("districts", [])) or (fam in a.get("families", []) and density == a.get("density"))
            if not hit:
                continue
            for key, value in f["values"].items():
                dimensional[key] = _rule(f, value=value)
        if uses or dimensional:
            out[d] = {"uses": uses, "dimensional": dimensional}
    return out


def write_review(facts: dict) -> None:
    lines = [
        "# Zoning review",
        "",
        "Tick a box **only after checking the fact against the linked code section**.",
        "Then run `uv run python -m pipeline.zoning.build_rules --apply`.",
        "Unticked facts stay out of the app (lots show *Needs planner review*).",
        "",
        "Legend for use cells: P = by right · A = administrator exception · S = special exception (ZBA) ·",
        "C = conditional use (Council) · - = not permitted (§ 911.01).",
        "",
    ]
    src = {"911": "https://ecode360.com/45476524", "903": "https://ecode360.com/45474237",
           "905": "https://ecode360.com/45474542", "912": "https://ecode360.com/45477814"}
    for title, group in (("Uses (§ 911.02 and related)", facts["use_facts"]),
                         ("Dimensional standards", facts["dimensional_facts"])):
        lines += [f"## {title}", ""]
        for f in group:
            box = "x" if f.get("reviewed") else " "
            link = src.get(f["section"][:3], "")
            what = ", ".join(f"{k} {v}" for k, v in (f.get("cells") or f.get("values") or {}).items())
            if f.get("frontage_rule"):
                fr = f["frontage_rule"]
                what = f"{fr['family']}: by right if lot width ≤ {fr['at_most_ft']} ft, else special exception"
            lines.append(f"- [{box}] `{f['id']}` — § {f['section']} ([code]({link}))  ")
            lines.append(f"  **{what}**  ")
            for q in f["quotes"]:
                lines.append(f"  > {q}  ")
            if f.get("reviewer_note"):
                lines.append(f"  _Note: {f['reviewer_note']}_")
            lines.append("")
    REVIEW.write_text("\n".join(lines), encoding="utf-8")


def apply_review(facts: dict) -> int:
    """Copy [x] ticks from REVIEW.md into facts.yaml, stamping who and when."""
    ticked = set(re.findall(r"^- \[[xX]\] `([^`]+)`", REVIEW.read_text(encoding="utf-8"), re.MULTILINE))
    who = _reviewer()
    now = datetime.now(UTC).date().isoformat()
    changed = 0
    for f in facts["use_facts"] + facts["dimensional_facts"]:
        want = f["id"] in ticked
        if want and not f.get("reviewed"):
            f.update(reviewed=True, reviewed_by=who, reviewed_on=now)
            changed += 1
        elif not want and f.get("reviewed"):
            f.update(reviewed=False)
            f.pop("reviewed_by", None)
            f.pop("reviewed_on", None)
            changed += 1
    return changed


def _reviewer() -> str:
    try:
        return subprocess.run(["git", "config", "user.name"], capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return getpass.getuser()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="copy ticks from REVIEW.md into facts.yaml first")
    args = ap.parse_args()
    cfg = load_config()
    text = FACTS.read_text(encoding="utf-8")
    header = "".join(line + "\n" for line in text.splitlines() if line.startswith("#"))
    facts = yaml.safe_load(text)
    verify(facts)
    if args.apply:
        n = apply_review(facts)
        FACTS.write_text(header + yaml.safe_dump(facts, sort_keys=False, allow_unicode=True, width=120), encoding="utf-8")
        print(f"applied review: {n} facts changed")
    districts = [d["district"] for d in json.loads((ROOT / cfg.zoning.priority_file).read_text(encoding="utf-8"))]
    rules = expand(facts, districts)
    path = ROOT / cfg.zoning.rules_file
    head = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.startswith("#")] if path.exists() else []
    body = yaml.safe_dump({"districts": rules}, sort_keys=False, allow_unicode=True, width=120)
    path.write_text("\n".join(head) + "\n" + body, encoding="utf-8")
    write_review(facts)
    reviewed = sum(1 for f in facts["use_facts"] + facts["dimensional_facts"] if f.get("reviewed"))
    total = len(facts["use_facts"]) + len(facts["dimensional_facts"])
    print(f"verified {total} facts ({reviewed} reviewed); wrote rules for {len(rules)} districts; wrote {REVIEW.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
