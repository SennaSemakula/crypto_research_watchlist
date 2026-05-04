"""Tests for the OI provider with caching + bybit fallback."""

from __future__ import annotations

from crypto_research_watchlist.data.openinterest_provider import OpenInterestProvider


def _row(value: float) -> dict:
    return {"openInterestValue": value, "openInterestAmount": value / 50_000.0}


class _FakeCcxt:
    def __init__(self, rows: list[dict] | None = None, raise_exc: bool = False) -> None:
        self.rows = rows or []
        self.calls = 0
        self.raise_exc = raise_exc

    def fetch_open_interest_history(self, symbol: str, timeframe: str, limit: int) -> list[dict]:
        self.calls += 1
        if self.raise_exc:
            raise RuntimeError("boom")
        return list(self.rows[-limit:])


def test_fetch_returns_today_and_7d_ago(tmp_path):
    # 24 prints. Provider takes [-1] for today and [-22] for 7d-ago.
    # Build rows so index 23 (today) = $1B and index 2 (-22 from 24) = $700M.
    rows = [_row(800_000_000) for _ in range(24)]
    rows[23] = _row(1_000_000_000)
    rows[2] = _row(700_000_000)
    bin_client = _FakeCcxt(rows=rows)
    provider = OpenInterestProvider(binance_perp=bin_client, cache_dir=tmp_path)
    out = provider.fetch("BTC-USD")
    assert out["open_interest_today"] == 1_000_000_000
    assert out["open_interest_7d_ago"] == 700_000_000


def test_fetch_falls_back_to_bybit(tmp_path):
    bin_client = _FakeCcxt(raise_exc=True)
    rows = [_row(500_000_000) for _ in range(24)]
    rows[23] = _row(900_000_000)
    rows[2] = _row(400_000_000)
    bybit_client = _FakeCcxt(rows=rows)
    provider = OpenInterestProvider(
        binance_perp=bin_client, bybit_perp=bybit_client, cache_dir=tmp_path,
    )
    out = provider.fetch("ETH-USD")
    assert out["open_interest_today"] == 900_000_000
    assert out["open_interest_7d_ago"] == 400_000_000


def test_inproc_cache(tmp_path):
    bin_client = _FakeCcxt(rows=[_row(1.0)] * 24)
    provider = OpenInterestProvider(binance_perp=bin_client, cache_dir=tmp_path)
    provider.fetch("BTC-USD")
    provider.fetch("BTC-USD")
    assert bin_client.calls == 1


def test_returns_empty_when_all_fail(tmp_path):
    bin_client = _FakeCcxt(raise_exc=True)
    bybit_client = _FakeCcxt(raise_exc=True)
    provider = OpenInterestProvider(
        binance_perp=bin_client, bybit_perp=bybit_client, cache_dir=tmp_path,
    )
    assert provider.fetch("DOT-USD") == {}
