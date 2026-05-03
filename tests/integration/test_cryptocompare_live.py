"""Live CryptoCompare News API integration tests.

Skipped by default. Run with:

    pytest -m integration tests/integration/test_cryptocompare_live.py

Requires CRYPTOCOMPARE_API_KEY in env (or .env). Hits the real
network against the free tier.
"""

from __future__ import annotations

import os

import pytest

from crypto_research_watchlist.news import sources

pytestmark = pytest.mark.integration


def _key_or_skip() -> str:
    key = os.environ.get("CRYPTOCOMPARE_API_KEY")
    if not key:
        pytest.skip("CRYPTOCOMPARE_API_KEY not set in environment")
    return key


def test_live_cryptocompare_returns_articles():
    _key_or_skip()
    out = sources.fetch_cryptocompare(limit=5)
    # At minimum a few well-formed records should come back.
    assert len(out) >= 1
    for art in out:
        assert art.source == "cryptocompare"
        assert art.url
        assert art.title
        assert art.published_at is not None
