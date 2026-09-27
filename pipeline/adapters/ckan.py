"""WPRDC CKAN adapters: datastore tables and downloadable files (GeoJSON)."""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

import requests

from core.config import ROOT, Config
from pipeline.adapters.base import AdapterResult, log, placeholder

RAW_DIR = ROOT / "data" / "raw"
PAGE = 32000  # WPRDC datastore_search max page size
TIMEOUT = 120
# WPRDC resets long paged pulls now and then. A page is retried with backoff
# so one reset costs a page, not the whole table.
RETRIES = 5
BACKOFF_SECONDS = 3


def _get(url: str, params: dict | None, source_id: str, what: str) -> requests.Response:
    """GET with retries and exponential backoff. Raises the last error."""
    for attempt in range(RETRIES):
        try:
            r = requests.get(url, params=params, timeout=TIMEOUT)
            r.raise_for_status()
            return r
        except requests.RequestException as e:
            if attempt == RETRIES - 1:
                raise
            wait = BACKOFF_SECONDS * 2 ** attempt
            log.warning("%s: %s failed (%s); retrying in %ds", source_id, what, e, wait)
            time.sleep(wait)
    raise AssertionError("unreachable")


class CkanDatastore:
    """Rows from a datastore table, with only the requested fields."""

    def __init__(self, source_id: str, fields: list[str], filters: dict | None = None):
        self.source_id = source_id
        self.fields = fields
        self.filters = filters or {}

    def describe(self) -> str:
        return f"CKAN datastore {self.source_id} fields={self.fields} filters={self.filters}"

    def distinct_values(self, config: Config, field: str, page: int = 100) -> list[str]:
        """Every distinct value of one column, paged in small sorted batches. Lets a
        caller split a large pull into shallow per-value queries, which the WPRDC
        datastore serves reliably where deep offsets get reset."""
        src = config.sources.sources[self.source_id]
        url = f"{config.sources.ckan_api}/datastore_search"
        out: list[str] = []
        offset = 0
        while True:
            params = {"resource_id": src.resource_id, "fields": field, "distinct": "true", "sort": field,
                      "limit": page, "offset": offset}
            recs = _get(url, params, self.source_id, f"distinct {field} at offset {offset}").json()["result"]["records"]
            out.extend(str(r[field]) for r in recs if r.get(field) is not None)
            if len(recs) < page:
                return out
            offset += page

    def fetch(self, config: Config) -> AdapterResult:
        src = config.sources.sources[self.source_id]
        # Two callers can read the same table with different columns or filters
        # (the parcel index wants vacant lots; comps want built ones). A cache keyed
        # on the source alone would hand the second caller the first one's rows.
        sig = hashlib.sha256(json.dumps([sorted(self.fields), self.filters], sort_keys=True).encode()).hexdigest()[:8]
        cache = RAW_DIR / f"{self.source_id}-{sig}.json"
        if cache.exists():
            log.info("%s: using cached %s", self.source_id, cache.name)
            return AdapterResult(self.source_id, json.loads(cache.read_text(encoding="utf-8")), "observed")
        url = f"{config.sources.ckan_api}/datastore_search"
        rows: list[dict] = []
        offset = 0
        try:
            while True:
                params = {
                    "resource_id": src.resource_id,
                    "limit": PAGE,
                    "offset": offset,
                    "fields": ",".join(self.fields),
                }
                if self.filters:
                    params["filters"] = json.dumps(self.filters)
                result = _get(url, params, self.source_id, f"page at offset {offset}").json()["result"]
                batch = result["records"]
                rows.extend(batch)
                log.info("%s: %d / %s rows", self.source_id, len(rows), result.get("total"))
                offset += PAGE
                if len(batch) < PAGE:
                    break
        except (requests.RequestException, KeyError, ValueError) as e:
            return placeholder(self.source_id, f"fetch failed: {e}", [])
        for row in rows:
            row.pop("_id", None)
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(rows), encoding="utf-8")
        return AdapterResult(self.source_id, rows, "observed")


class CkanDownload:
    """A resource file (e.g., GeoJSON) resolved through resource_show."""

    def __init__(self, source_id: str, suffix: str = ".geojson"):
        self.source_id = source_id
        self.suffix = suffix

    def describe(self) -> str:
        return f"CKAN file download {self.source_id}"

    def fetch(self, config: Config) -> AdapterResult:
        src = config.sources.sources[self.source_id]
        path = RAW_DIR / f"{self.source_id}{self.suffix}"
        if not path.exists():
            try:
                meta = _get(f"{config.sources.ckan_api}/resource_show", {"id": src.resource_id},
                            self.source_id, "resource_show")
                file_url = meta.json()["result"]["url"]
                r = _get(file_url, None, self.source_id, "file download")
            except (requests.RequestException, KeyError, ValueError) as e:
                return placeholder(self.source_id, f"download failed: {e}", None)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(r.content)
        return AdapterResult(self.source_id, Path(path), "observed")
