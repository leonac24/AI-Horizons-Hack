"""Regenerate docs/SOURCES.md and the auto section of docs/LIMITATIONS.md.

    uv run python -m pipeline.docs
"""

from __future__ import annotations

import json
import re
from collections import Counter

from core.config import ROOT, load_config
from core.zoning import covered_bases, in_force, load_rules

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
              ("- `census_bulk` and `arcgis` sources are joined by `uv run python -m pipeline.enrich_context` "
               "or during a full parcel rebuild. Official Census summary tables need no API key. "
               "Large raw geometry downloads are gitignored; derived site facts are published."),
              ("- `manual` means the pipeline does not download that source. Published HUD FY2026 MFI "
               "was verified and transcribed into assumptions.yaml; other manual sources may still be unconnected."), ""]
    return "\n".join(lines)


def limitations_auto(cfg) -> str:
    rules = load_rules(cfg)
    idx_path = ROOT / "data" / "processed" / "parcels.json"
    report_path = ROOT / "data" / "processed" / "pipeline_report.json"
    counts = json.loads(report_path.read_text(encoding="utf-8")).get("counts", {}) if report_path.exists() else {}
    parcels = json.loads(idx_path.read_text(encoding="utf-8"))["parcels"].values() if idx_path.exists() else []
    # Use rules hang off the base district, so parcels are counted that way too —
    # reviewing R1D covers every R1D-* code at once.
    def _base(code):
        return cfg.zoning.district_code.split(code)[0] or "(no district)"

    by_district = Counter(_base(p.get("zoning")) for p in parcels)

    covered_b = covered_bases(cfg, rules)
    human_b = covered_bases(cfg, rules, human_only=True)
    citywide = [u for u, r in ((rules.get("citywide") or {}).get("uses") or {}).items() if in_force(cfg, r)]
    total = sum(by_district.values()) or 1
    covered = sum(n for d, n in by_district.items() if d in covered_b)
    human = sum(n for d, n in by_district.items() if d in human_b)
    placeholders = [k for k, a in cfg.assumptions.items() if a.provenance == "placeholder"]
    unverified = [s.name for s in cfg.sources.sources.values() if s.verified is False]
    top_uncovered = [f"{d} ({n:,})" for d, n in by_district.most_common() if d not in covered_b][:12]
    mode = ("only human-reviewed rules are in force" if cfg.zoning.require_human_review else
            "AI-extracted rules are in force once their quotes verify against the saved code text; "
            "they are labelled as not checked by a planner")
    return "\n".join([
        START,
        f"_Auto-generated for config `{cfg.hash}`._",
        "",
        f"- **Vacant parcels indexed:** {total:,} (City of Pittsburgh only).",
        f"- **Zoning rules in force:** {mode} (`require_human_review` in zoning.yaml).",
        (f"- **Share of vacant parcels covered by zoning rules:** {covered / total:.1%} "
         f"({len(covered_b)} of {len(by_district)} base districts); "
         f"by human-reviewed rules: {human / total:.1%}."),
        f"- **Largest base districts with no rules yet:** {', '.join(top_uncovered) or 'none'}.",
        (f"- **Uses settled city-wide ({len(citywide)}):** {', '.join(f'`{u}`' for u in citywide) or 'none'}"
         + (". These are decided by a rule that applies in every district, "
            "so they are excluded from the ranking everywhere, with a citation." if citywide else ".")),
        f"- **Placeholder assumptions ({len(placeholders)}):** {', '.join(f'`{p}`' for p in placeholders) or 'none'}.",
        (f"- **2024 ACS median income / renter burden:** {counts.get('acs_income_values', 0):,} / "
         f"{counts.get('acs_renter_burden_values', 0):,} indexed lots have tract estimates."),
        (f"- **FEMA point screen:** {counts.get('fema_classified', 0):,} classified; "
         f"{counts.get('fema_sfha_flagged', 0):,} in a mapped Special Flood Hazard Area at the tested point."),
        (f"- **2018 PWSA combined sewersheds:** {counts.get('combined_sewershed_matched', 0):,} "
         "indexed lots have a point match."),
        (f"- **EPA SLD transit access:** {counts.get('transit_access_matched', 0):,} indexed lots have "
         "a 2021 block-group match (D5DRI relative access; D5BR weighted jobs within 45 minutes)."),
        (f"- **County geometry dimensions:** {counts.get('geometry_dimensions_estimated', 0):,} lots "
         "have modeled parcel axes where legal dimensions were absent; these are not survey dimensions."),
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
