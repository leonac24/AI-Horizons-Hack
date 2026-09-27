"""WPRDC CKAN adapters: datastore tables and downloadable files (GeoJSON)."""

from __future__ import annotations

import json
from pathlib import Path

import requests

from core.config import ROOT, Config
from pipeline.adapters.base import AdapterResult, log, placeholder

RAW_DIR = ROOT / "data" / "raw"
PAGE = 32000  # WPRDC datastore_search max page size
TIMEOUT = 120


class CkanDatastore:
    """Rows from a datastore table, with only the requested fields."""

    def __init__(self, source_id: str, fields: list[str], filters: dict | None = None):
        self.source_id = source_id
        self.fields = fields
        self.filters = filters or {}

    def describe(self) -> str:
        return f"CKAN datastore {self.source_id} fields={self.fields} filters={self.filters}"

    def fetch(self, config: Config) -> AdapterResult:
        src = config.sources.sources[self.source_id]
        cache = RAW_DIR / f"{self.source_id}.json"
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
                r = requests.get(url, params=params, timeout=TIMEOUT)
                r.raise_for_status()
                result = r.json()["result"]
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
                meta = requests.get(
                    f"{config.sources.ckan_api}/resource_show",
                    params={"id": src.resource_id},
                    timeout=TIMEOUT,
                )
                meta.raise_for_status()
                file_url = meta.json()["result"]["url"]
                r = requests.get(file_url, timeout=TIMEOUT)
                r.raise_for_status()
            except (requests.RequestException, KeyError, ValueError) as e:
                return placeholder(self.source_id, f"download failed: {e}", None)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(r.content)
        return AdapterResult(self.source_id, Path(path), "observed")
