"""Build assessment comparables for core/tax.py.

    uv run python -m pipeline.build_comps

Reads the same county assessment table the parcel index uses, keeps only the use
classes tax.yaml declares, joins each comp to its city neighborhood through the
parcel centroid file, and writes the comps table (path: tax.yaml comps.file).
Needs `uv sync --group pipeline`.
"""

from __future__ import annotations

import json
import logging
import re

import pandas as pd

from core.config import ROOT, Config, load_config
from pipeline.adapters.ckan import CkanDatastore
from pipeline.steps.comps import aggregate_comps

log = logging.getLogger("pipeline")


def build(cfg: Config) -> dict:
    pc = cfg.parcels
    comps = cfg.tax.comps
    use_col = next(k for k, v in comps.fields.items() if v == "use_class")
    muni_col = pc["municipality_field"]
    muni = re.compile(pc["municipality_pattern"])
    # The county table is large and WPRDC resets deep offsets, so the pull is split
    # into one small query per (use class, city municipality). Each caches on its
    # own; a dropped connection costs one small query, not the table.
    table_all = CkanDatastore(pc["assessments_source"], list(comps.fields))
    munis = [m for m in table_all.distinct_values(cfg, muni_col) if muni.search(m)]
    if not munis:
        raise SystemExit(f"no values of {muni_col} match city.yaml municipality_pattern — cannot build comps")
    log.info("%d city municipalities x %d use classes", len(munis), len(comps.use_classes))
    raw_rows: list[dict] = []
    for uc in comps.use_classes:
        for m in munis:
            res = CkanDatastore(pc["assessments_source"], list(comps.fields), {use_col: [uc], muni_col: [m]}).fetch(cfg)
            if not res.ok:
                raise SystemExit(f"assessments unavailable for {uc!r} in {m!r} — cannot build comps")
            raw_rows.extend(res.data)
    if not raw_rows:
        raise SystemExit("no assessment rows for any declared use class — cannot build comps")
    df = pd.DataFrame(raw_rows).rename(columns=comps.fields).drop(columns=["municipality"])

    cf = pc["centroid_fields"]
    cent = CkanDatastore(pc["centroids_source"], list(cf), pc["centroids_filter"]).fetch(cfg)
    if cent.ok:
        cdf = pd.DataFrame(cent.data).rename(columns=cf)[["id", "neighborhood"]].drop_duplicates("id")
        df = df.merge(cdf, on="id", how="left")
    else:
        df["neighborhood"] = None
    rows = df.astype(object).where(df.notna(), None).to_dict(orient="records")

    table = aggregate_comps(cfg, rows)
    out = ROOT / comps.file
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(table, indent=1), encoding="utf-8")
    for tid, t in table["by_typology"].items():
        cw = t["citywide"] or {}
        log.info("%s: citywide n=%s median=%s; %d neighborhoods with >= %d comps",
                 tid, cw.get("n"), cw.get("value"), len(t["neighborhoods"]), comps.min_comps)
    log.info("wrote %s", out)
    return table


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    build(load_config())
