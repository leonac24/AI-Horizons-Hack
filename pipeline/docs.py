"""Regenerate docs/SOURCES.md and the auto section of docs/LIMITATIONS.md.

    uv run python -m pipeline.docs
"""

from __future__ import annotations

import json
import re
from collections import Counter

from core.config import ROOT, load_config
from core.zoning import load_rules

DOCS = ROOT / "docs"
START, END = "<!-- AUTO:START -->", "<!-- AUTO:END -->"


def sources_md(cfg) -> str:
    lines = ["# Data sources", "",
             ("Generated from `data/config/sources.yaml` by `uv run python -m pipeline.docs`. "
             "Do not edit by hand."), "",
             "| id | Dataset | Publisher | Vintage | License | Verified | Notes |",
             "|---|---|---|---|---|---|---|"]
    for sid, s in cfg.sources.sources.items():
        name = f"[{s.name}]({s.url})" if s.url else s.name
        ver = s.verified if s.verified else "not yet"
        lines.append(f"| `{sid}` | {name} | {s.publisher} | {s.vintage} | {s.license} | {ver} | {s.note or ''} |")
    lines += ["", "## How the pipeline fetches them", "",
              ("- `ckan_datastore` / `ckan_download` sources are fetched by `uv run python -m pipeline.build_parcels` "
              "(after `uv sync --group pipeline`). Downloads are cached in `data/raw/` (gitignored)."),
              ("- `manual` sources are not scripted yet; see the note on each. Until they are connected the values that "
              "depend on them are marked **placeholder** in the app."), ""]
    return "\n".join(lines)


def limitations_auto(cfg) -> str:
    rules = load_rules(cfg)
    idx_path = ROOT / "data" / "processed" / "parcels.json"
    parcels = json.loads(idx_path.read_text(encoding="utf-8"))["parcels"].values() if idx_path.exists() else []
    # Use rules hang off the base district, so parcels are counted that way too —
    # reviewing R1D covers every R1D-* code at once.
    def _base(code):
        return cfg.zoning.district_code.split(code)[0] or "(no district)"

    by_district = Counter(_base(p.get("zoning")) for p in parcels)

    def _has_reviewed_use(r):
        return any(u.get("reviewed") for u in (r.get("uses") or {}).values())

    reviewed = {d for d, r in (rules.get("districts") or {}).items() if _has_reviewed_use(r)}
    # City-wide uses (Chapter 912) are not a district and must not be counted as
    # coverage — they answer one use everywhere, not one district's whole table.
    citywide = [u for u, r in ((rules.get("citywide") or {}).get("uses") or {}).items() if r.get("reviewed")]
    total = sum(by_district.values()) or 1
    covered = sum(n for d, n in by_district.items() if d in reviewed)
    placeholders = [k for k, a in cfg.assumptions.items() if a.provenance == "placeholder"]
    unverified = [s.name for s in cfg.sources.sources.values() if s.verified is False]
    top_unreviewed = [f"{d} ({n:,})" for d, n in by_district.most_common() if d not in reviewed][:12]
    return "\n".join([
        START,
        f"_Auto-generated for config `{cfg.hash}`._",
        "",
        f"- **Vacant parcels indexed:** {total:,} (City of Pittsburgh only).",
        (f"- **Share of vacant parcels covered by human-reviewed zoning rules:** {covered / total:.1%} "
        f"({len(reviewed)} of {len(by_district)} districts reviewed)."),
        f"- **Largest unreviewed base districts:** {', '.join(top_unreviewed) or 'none'}.",
        (f"- **Uses settled city-wide ({len(citywide)}):** {', '.join(f'`{u}`' for u in citywide) or 'none'}"
         + (". These are decided by a reviewed rule that applies in every district, "
            "so they are excluded from the ranking everywhere, with a citation." if citywide else ".")),
        f"- **Placeholder assumptions ({len(placeholders)}):** {', '.join(f'`{p}`' for p in placeholders) or 'none'}.",
        f"- **Sources not yet connected ({len(unverified)}):** {', '.join(unverified) or 'none'}.",
        END,
    ])


def main() -> None:
    cfg = load_config()
    DOCS.mkdir(exist_ok=True)
    (DOCS / "SOURCES.md").write_text(sources_md(cfg), encoding="utf-8")
    lim = DOCS / "LIMITATIONS.md"
    text = lim.read_text(encoding="utf-8") if lim.exists() else f"# Limitations\n\n{START}\n{END}\n"
    text = re.sub(re.escape(START) + ".*?" + re.escape(END), limitations_auto(cfg), text, flags=re.DOTALL)
    lim.write_text(text, encoding="utf-8")
    print("wrote docs/SOURCES.md and updated docs/LIMITATIONS.md")


if __name__ == "__main__":
    main()
