"""Contract tests for the HTTP surface: limits, caching, and error handling.

These exist because the API is public and unauthenticated. Each test pins a
promise made in docs/BACKEND.md.
"""

import pytest
from fastapi.testclient import TestClient

from core.config import get_config
from server.app import _RateLimiter, app

client = TestClient(app, raise_server_exceptions=False)


def _any_parcel_id() -> str | None:
    from server.app import _index
    ids = list(_index()["parcels"])
    return ids[0] if ids else None


def test_health_reports_config_hash():
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["config_hash"] == get_config().hash


def test_security_headers_on_every_response():
    r = client.get("/api/health")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["referrer-policy"] == "no-referrer"


def test_config_does_not_leak_server_paths():
    """The browser needs labels and criteria, not our filesystem layout."""
    zoning = client.get("/api/config").json()["zoning"]
    assert "rules_file" not in zoning
    assert "priority_file" not in zoning
    assert "raw_text_dir" not in zoning["code"]


def test_config_is_conditionally_cacheable():
    first = client.get("/api/config")
    etag = first.headers["etag"]
    again = client.get("/api/config", headers={"If-None-Match": etag})
    assert again.status_code == 304


def test_search_rejects_oversized_limit():
    assert client.get("/api/parcels/search", params={"q": "00", "limit": 10_000}).status_code == 422


def test_search_rejects_short_query():
    assert client.get("/api/parcels/search", params={"q": "0"}).status_code == 422


def test_malformed_parcel_id_is_rejected_not_looked_up():
    # Lowercase and punctuation cannot be a county PIN; reject at the edge.
    assert client.get("/api/analysis/../../etc/passwd").status_code in (404, 422)
    assert client.get("/api/analysis/abc!def").status_code == 422


def test_unknown_parcel_404_says_nothing_about_internals():
    r = client.get("/api/analysis/ZZZZ0000000000ZZ")
    assert r.status_code == 404
    assert "parcels.json" not in r.text and "Traceback" not in r.text


def test_explain_rejects_oversized_payload():
    r = client.post("/api/explain", json={
        "parcel_id": "0009G00180000000",
        "weights": {f"w{i}": 1 for i in range(500)},
        "ranking": [],
    })
    assert r.status_code in (413, 422)


def test_rate_limiter_opens_and_closes():
    rl = _RateLimiter(per_minute=2)
    assert rl.check("ip", now=0.0)
    assert rl.check("ip", now=1.0)
    assert not rl.check("ip", now=2.0)      # third call inside the window
    assert rl.check("ip", now=61.0)         # window has rolled
    assert rl.check("other", now=2.0)       # limits are per client


def test_analysis_is_idempotent_and_etagged():
    pid = _any_parcel_id()
    if pid is None:
        pytest.skip("no parcel index built")
    a = client.get(f"/api/analysis/{pid}")
    b = client.get(f"/api/analysis/{pid}")
    assert a.status_code == 200
    assert a.json() == b.json(), "same parcel + same config must give the same analysis"
    assert client.get(f"/api/analysis/{pid}",
                      headers={"If-None-Match": a.headers["etag"]}).status_code == 304


def test_routes_answer_with_and_without_the_api_prefix():
    """Hosts differ on whether the function sees the rewritten path."""
    assert client.get("/api/health").status_code == 200
    assert client.get("/health").status_code == 200
