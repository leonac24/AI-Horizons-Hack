# Data sources

Generated from `data/config/sources.yaml` by `uv run python -m pipeline.docs`. Do not edit by hand.

| id | Dataset | Publisher | Vintage | License | Verified | Notes |
|---|---|---|---|---|---|---|
| `wprdc_assessments` | [Allegheny County Property Assessments](https://data.wprdc.org/dataset/property-assessments) | Allegheny County Office of Property Assessments via WPRDC | current extract (fetched at pipeline run) | see WPRDC dataset page | 2026-09-26 | Assessed/fair-market values are not market prices. Owner name and owner mailing address fields are never fetched. |
| `wprdc_parcel_centroids` | [Parcel Centroids in Allegheny County with Geographic Identifiers](https://data.wprdc.org/dataset/parcel-centroids-in-allegheny-county-with-geographic-identifiers) | WPRDC | March 2025 | Creative Commons CCZero | 2026-09-26 | Point per parcel with census tract, block group and city neighborhood. Centroid may fall outside irregular parcels. |
| `wprdc_city_owned` | [City-Owned Properties](https://data.wprdc.org/dataset/city-owned-properties) | City of Pittsburgh via WPRDC | current extract (fetched at pipeline run) | see WPRDC dataset page | 2026-09-26 | Ownership is not availability — check disposition status with the City / Land Bank. |
| `wprdc_zoning` | [Pittsburgh Zoning Districts](https://data.wprdc.org/dataset/zoning) | City of Pittsburgh via WPRDC | current extract (fetched at pipeline run) | see WPRDC dataset page | 2026-09-26 | Base districts only. Overlays (e.g., Riverfront, IPOD) are separate layers not yet joined. |
| `wprdc_neighborhoods` | [Pittsburgh Neighborhoods](https://data.wprdc.org/dataset/neighborhoods2) | City of Pittsburgh via WPRDC | current extract | Creative Commons Attribution | 2026-09-26 |  |
| `wprdc_steep_slope` | [Pittsburgh 25% or Greater Slope](https://data.wprdc.org/dataset/25-or-greater-slope) | City of Pittsburgh via WPRDC | current extract | see WPRDC dataset page | 2026-09-26 | Derived threshold layer, tested at the parcel centroid only. |
| `wprdc_landslide_prone` | [Pittsburgh Landslide Prone Areas](https://data.wprdc.org/dataset/landslide-prone-areas) | City of Pittsburgh via WPRDC | current extract | see WPRDC dataset page | 2026-09-26 | Screening layer; tested at the parcel centroid only. |
| `wprdc_undermined` | [Pittsburgh Undermined Areas](https://data.wprdc.org/dataset/undermined-areas) | City of Pittsburgh via WPRDC | current extract | see WPRDC dataset page | 2026-09-26 | Historic mine maps are incomplete; never a safety determination. |
| `pgh_zoning_code` | [Pittsburgh Code of Ordinances, Title Nine — Zoning Code](https://ecode360.com/45474054) | City of Pittsburgh (hosted by General Code / eCode360) | as amended (retrieval date recorded per rule) | public law | 2026-09-26 |  |
| `hud_income_limits` | [HUD Income Limits (Pittsburgh, PA HUD Metro FMR Area)](https://www.huduser.gov/portal/datasets/il.html) | U.S. Department of Housing and Urban Development | not yet retrieved | public domain | not yet | huduser.gov blocked scripted requests on 2026-09-26. |
| `hud_chas` | [Comprehensive Housing Affordability Strategy (CHAS)](https://www.huduser.gov/portal/datasets/cp.html) | HUD | not yet retrieved | public domain | not yet |  |
| `acs_5yr` | [American Community Survey 5-Year Estimates](https://www.census.gov/data/developers/data-sets/acs-5year.html) | U.S. Census Bureau | not yet retrieved | public domain | not yet | The Census API now requires a (free) key — set CENSUS_API_KEY. |
| `prt_gtfs` | [Pittsburgh Regional Transit GTFS](https://data.wprdc.org/dataset/port-authority-of-allegheny-county-transit-data) | Pittsburgh Regional Transit via WPRDC | not yet retrieved | see WPRDC dataset page | not yet |  |
| `fema_nfhl` | [FEMA National Flood Hazard Layer](https://www.fema.gov/flood-maps/national-flood-hazard-layer) | FEMA | not yet retrieved | public domain | not yet |  |
| `alcosan_cso` | ALCOSAN / PWSA combined sewer overflow data | ALCOSAN / PWSA | not yet retrieved | unknown | not yet |  |
| `epa_egrid` | [EPA eGRID](https://www.epa.gov/egrid) | U.S. EPA | not yet retrieved | public domain | not yet |  |
| `epa_smart_location` | [EPA Smart Location Database](https://www.epa.gov/smartgrowth/smart-location-mapping) | U.S. EPA | not yet retrieved | public domain | not yet |  |
| `nrel_resstock` | [ResStock](https://resstock.nrel.gov/) | U.S. DOE / NREL | not yet retrieved | public | not yet |  |

## How the pipeline fetches them

- `ckan_datastore` / `ckan_download` sources are fetched by `uv run python -m pipeline.build_parcels` (after `uv sync --group pipeline`). Downloads are cached in `data/raw/` (gitignored).
- `manual` sources are not scripted yet; see the note on each. Until they are connected the values that depend on them are marked **placeholder** in the app.
