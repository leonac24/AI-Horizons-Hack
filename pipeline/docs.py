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
    parcels = json.loads(idx_path.read_text())["parcels"].values() if idx_path.exists() else []
    by_district = Counter(p.get("zoning") or "(no district)" for p in parcels)
    reviewed = {d for d, r in rules.items() if any(u.get("reviewed") for u in (r.get("uses") or {}).values())}
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
        f"- **Largest unreviewed districts:** {', '.join(top_unreviewed) or 'none'}.",
        f"- **Placeholder assumptions ({len(placeholders)}):** {', '.join(f'`{p}`' for p in placeholders) or 'none'}.",
        f"- **Sources not yet connected ({len(unverified)}):** {', '.join(unverified) or 'none'}.",
        END,
    ])


def main() -> None:
    cfg = load_config()
    DOCS.mkdir(exist_ok=True)
    (DOCS / "SOURCES.md").write_text(sources_md(cfg))
    lim = DOCS / "LIMITATIONS.md"
    text = lim.read_text() if lim.exists() else f"# Limitations\n\n{START}\n{END}\n"
    text = re.sub(re.escape(START) + ".*?" + re.escape(END), limitations_auto(cfg), text, flags=re.DOTALL)
    lim.write_text(text)
    print("wrote docs/SOURCES.md and updated docs/LIMITATIONS.md")


if __name__ == "__main__":
    main()
