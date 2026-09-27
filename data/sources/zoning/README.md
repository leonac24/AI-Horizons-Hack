# Zoning code snapshots

Verbatim excerpts of the Pittsburgh Zoning Code (Title Nine) read on eCode360 on
2026-09-26 through a browser (eCode360 blocks scripted requests). Whitespace is
collapsed in the original excerpts. The 903.01–903.02 and Chapter 904 captures
preserve the indexed page's line breaks and include source metadata. Compare
them against the live code before relying on them. Tables in 903.03 and 905.0x
are flattened in page order, as the site renders them. The use table (911-02)
is a cell-by-cell transcription in column order, because its flattened page
text drops empty cells and loses alignment;
the definition sentences in it are verbatim.
Every `quote` in `pipeline/zoning/facts.yaml` must appear verbatim in one of
these files; `pipeline/zoning/build_rules.py` fails otherwise.

| File | Section | Source |
|---|---|---|
| 903-01-02_use-subdistricts.txt | §§ 903.01–903.02 | https://ecode360.com/45474194 |
| 911-01_use-table-legend.txt | § 911.01 | https://ecode360.com/45476524 |
| 911-02_use-table-residential.txt | § 911.02 (residential rows) | https://ecode360.com/45476524 |
| 911-04-A-69_single-unit.txt | § 911.04.A.69, A.69A | https://ecode360.com/45476524 |
| 903-03_development-subdistricts.txt | § 903.03 | https://ecode360.com/45474237 |
| 904_mixed-use.txt | Chapter 904 | https://ecode360.com/45474350 |
| 905-01_P-parks.txt | § 905.01 | https://ecode360.com/45474542 |
| 905-02_H-hillside.txt | § 905.02 | https://ecode360.com/45474542 |
| 912-08_ADU-overlay.txt | § 912.08 | https://ecode360.com/45477814 |

The repository also tracks these curated files under `data/raw/zoning/`, added
for the separate LLM extraction workflow (`pipeline/zoning/extract.py`). They
are included in the local Laya classification compile. Newly added files under
`data/raw/` are ignored by default.

| File | Section | Source |
|---|---|---|
| 903.02.txt | § 903.02 | https://ecode360.com/45474194 |
| 903.03.txt | § 903.03 | https://ecode360.com/45474237 |
| 905.01.txt | § 905.01 | https://ecode360.com/45474542 |
| 905.02.txt | § 905.02 | https://ecode360.com/45474542 |
| 911.02.txt | § 911.02 | https://ecode360.com/45476524 |
| 911.04.txt | § 911.04 | https://ecode360.com/45476524 |
| 912.08.txt | § 912.08 | https://ecode360.com/45477814 |

Public law; retrieved 2026-09-26. Confirm against the current code before relying on it.
