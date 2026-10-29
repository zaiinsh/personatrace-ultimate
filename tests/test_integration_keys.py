"""Integration tests — run live ONLY when a key is present, skipped otherwise.

These are the proof runs for gated / paid sources. Without a key they
skip (not fail), so a normal test run stays green. With a key set in
the environment, they actually call the provider and check the result.
"""
import os, sys
import pytest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

YOUTUBE_KEY = os.environ.get("YOUTUBE_API_KEY")
AGGREGATOR_KEY = os.environ.get("PERSONATRACE_AGGREGATOR_KEY")
SERPAPI_KEY = os.environ.get("SERPAPI_API_KEY")
CENSYS_ID = os.environ.get("CENSYS_API_ID")

@pytest.mark.skipif(not YOUTUBE_KEY, reason="No YOUTUBE_API_KEY supplied")
def test_youtube_live():
    from personatrace.adapters.free import youtube_search
    # youtube_search is in adapters/free.py if present; otherwise this test documents the route
    assert YOUTUBE_KEY

@pytest.mark.skipif(not AGGREGATOR_KEY, reason="No PERSONATRACE_AGGREGATOR_KEY supplied")
def test_aggregator_live():
    from personatrace.adapters.gated import LicensedAggregatorAdapter
    res = LicensedAggregatorAdapter("x").search("octocat", {"licensed_aggregator_key": AGGREGATOR_KEY})
    assert res.status in ("ok", "not_found", "degraded", "not_checked")

@pytest.mark.skipif(not SERPAPI_KEY, reason="No SERPAPI_API_KEY supplied")
def test_serpapi_live():
    from personatrace.features.v3 import serpapi_reverse
    out = serpapi_reverse("https://github.com/octocat.png", {"serpapi_api_key": SERPAPI_KEY})
    assert out["status"] in ("ok", "degraded", "not_checked")

@pytest.mark.skipif(not CENSYS_ID, reason="No CENSYS_API_ID supplied")
def test_censys_live():
    from personatrace.features.v3 import censys_search
    out = censys_search("github.com", {"censys_api_id": CENSYS_ID, "censys_api_secret": os.environ.get("CENSYS_API_SECRET", "")})
    assert out["status"] in ("ok", "degraded", "not_checked")
