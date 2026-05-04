"""Per-signal diagnostic explainer.

Used by ``python -m crypto_research_watchlist diagnose`` to answer the
question: WHY did the technical / funding / OI / on-chain / cross-asset
signal return what it did for this symbol on this run?

The daily Telegram message previously read like a database dump; signals
all returned strength=0 for every coin and the reason was buried in
provider failures + stale parquet. This module surfaces exactly that.

Output shape (one block per symbol):

    BTC-USD
      parquet: latest=2026-05-01 (2 days stale, today=2026-05-03)
      technical: MACD line=0.012 signal=0.008 -> bullish, strength=+0.30 -> BULLISH
      funding_rate: provider returned None -> NO_DATA (no funding data)
      open_interest: oi_today=None -> NO_DATA (provider returned None)
      onchain: active_addresses_z=None, netflow=None -> NO_DATA
      cross_asset: rel_strength_60d=-0.18 -> BEARISH, strength=-0.25
      score: 47.3 -> WATCH (thresholds STRONG>=72 / WATCH>=55 / AVOID<40)

Pure: no Telegram, no DB writes. Safe to call before/after a daily run.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from .candidates import build_candidate
from .config import AppConfig, EnvSettings
from .pipeline import (
    DEFAULT_PARQUET,
    _annualised_vol,
    _drawdown_30d,
    parquet_price_loader,
)
from .signals import (
    LABEL_NO_DATA,
    SignalContext,
    SignalResult,
    evaluate_all,
)
from .universe import build_universe, filter_universe

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Per-signal explainer functions. Each returns a single string describing
# WHY the result is what it is. The output is the same shape across all
# signals so the operator can scan a column.
# ---------------------------------------------------------------------------


def _explain_technical(sig: SignalResult) -> str:
    d = sig.details or {}
    parts: list[str] = []
    if "rsi14" in d:
        parts.append(f"RSI14={d['rsi14']:.0f}")
    if "macd" in d:
        m = d["macd"]
        parts.append(f"MACD line={m.get('line')} signal={m.get('signal')}")
    if "ema_cross" in d:
        parts.append(f"EMA={d['ema_cross']}")
    if "volume_ratio" in d:
        parts.append(f"vol={d['volume_ratio']}x")
    if not parts:
        return f"no technical inputs computed -> {sig.label}"
    return f"{', '.join(parts)} -> strength={sig.strength:+.2f} -> {sig.label}"


def _explain_funding(sig: SignalResult) -> str:
    d = sig.details or {}
    if sig.label == LABEL_NO_DATA or "reason" in d:
        return f"NO_DATA ({d.get('reason', 'unknown')})"
    if "median_8h" in d:
        return (
            f"median_8h={d['median_8h']:+.6f} "
            f"(samples={d.get('samples', '?')}) "
            f"-> strength={sig.strength:+.2f} -> {sig.label}"
        )
    return f"strength={sig.strength:+.2f} -> {sig.label}"


def _explain_oi(sig: SignalResult) -> str:
    d = sig.details or {}
    if sig.label == LABEL_NO_DATA or "reason" in d:
        return f"NO_DATA ({d.get('reason', 'unknown')})"
    return (
        f"oi_delta_7d={d.get('oi_delta_7d')} "
        f"price_delta_7d={d.get('price_delta_7d')} "
        f"-> strength={sig.strength:+.2f} -> {sig.label}"
    )


def _explain_onchain(sig: SignalResult) -> str:
    d = sig.details or {}
    if sig.label == LABEL_NO_DATA or ("reason" in d and not sig.bullets):
        return f"NO_DATA ({d.get('reason', 'unknown')})"
    z = d.get("active_addresses_z")
    nf = d.get("exchange_netflow_usd_7d")
    return (
        f"active_addr_z={z} netflow_7d=${nf} "
        f"-> strength={sig.strength:+.2f} -> {sig.label}"
    )


def _explain_cross_asset(sig: SignalResult) -> str:
    d = sig.details or {}
    if "reason" in d and not sig.bullets:
        return f"NO_DATA ({d.get('reason', 'unknown')})"
    parts: list[str] = []
    if "rel_strength_60d" in d:
        parts.append(f"rs60d={d['rel_strength_60d']:+.2%}")
    if "rel_strength_30d" in d:
        parts.append(f"rs30d={d['rel_strength_30d']:+.2%}")
    if "eth_btc_ratio_change_30d" in d:
        parts.append(f"ETH/BTC_30d={d['eth_btc_ratio_change_30d']:+.2%}")
    inputs = ", ".join(parts) if parts else "no cross inputs"
    return f"{inputs} -> strength={sig.strength:+.2f} -> {sig.label}"


_EXPLAINERS = {
    "technical": _explain_technical,
    "funding_rate": _explain_funding,
    "open_interest": _explain_oi,
    "onchain": _explain_onchain,
    "cross_asset": _explain_cross_asset,
}


# ---------------------------------------------------------------------------
# Top-level entrypoint
# ---------------------------------------------------------------------------


def _parquet_freshness(parquet_path: Path = DEFAULT_PARQUET) -> str:
    if not parquet_path.exists():
        return "parquet: MISSING"
    try:
        df = pd.read_parquet(parquet_path, columns=["date"])
        latest = pd.to_datetime(df["date"]).max()
        today = datetime.now(UTC).date()
        delta = (today - latest.date()).days
        marker = "fresh" if delta <= 1 else f"{delta} days stale"
        return f"parquet: latest={latest.date()} ({marker}, today={today})"
    except Exception as exc:  # pragma: no cover
        return f"parquet: read failed ({exc})"


def _resolve_loaders(env: EnvSettings):
    """Wire the same providers the daily ``run`` command uses.

    Each loader is fail-safe: any exception inside the provider returns
    None / [] / {} and the corresponding signal will surface as NO_DATA.
    """
    from .data.etherscan_provider import SYMBOL_TO_CHAIN, EtherscanProvider
    from .data.funding_provider import FundingRateProvider
    from .data.onchain_provider import OnChainProvider
    from .data.openinterest_provider import OpenInterestProvider

    fp = FundingRateProvider()
    oip = OpenInterestProvider()
    ocp = OnChainProvider()
    esp = EtherscanProvider(api_key=env.etherscan_api_key)

    def funding_loader(symbol: str):
        try:
            return fp.last_24h(symbol)
        except Exception:
            return None

    def oi_loader(symbol: str):
        try:
            return oip.fetch(symbol)
        except Exception:
            return {}

    def onchain_loader(symbol: str):
        try:
            snap = ocp.fetch(symbol)
            base = {
                "active_addresses_z": snap.active_addresses_z,
                "exchange_netflow_usd_7d": snap.exchange_netflow_usd_7d,
            }
        except Exception:
            base = {"active_addresses_z": None, "exchange_netflow_usd_7d": None}

        if symbol not in SYMBOL_TO_CHAIN:
            return base
        try:
            es = esp.fetch_chain_stats(symbol) or {}
        except Exception:
            es = {}
        if es.get("active_addresses_z") is not None:
            base["active_addresses_z"] = es["active_addresses_z"]
        return base

    return funding_loader, oi_loader, onchain_loader


def run_diagnose(
    *,
    cfg: AppConfig,
    env: EnvSettings,
    symbols: str | None = None,
    price_loader=None,
    funding_loader=None,
    oi_loader=None,
    onchain_loader=None,
) -> str:
    """Produce a multi-line diagnostic report. Returns the report string.

    Loaders default to the production providers (with try/except guards).
    Tests inject stubs to keep things offline.
    """
    price_loader = price_loader or parquet_price_loader()
    if funding_loader is None or oi_loader is None or onchain_loader is None:
        f_def, o_def, oc_def = _resolve_loaders(env)
        funding_loader = funding_loader or f_def
        oi_loader = oi_loader or o_def
        onchain_loader = onchain_loader or oc_def

    universe = filter_universe(cfg, build_universe(cfg))
    if symbols:
        wanted = {s.strip().upper() for s in symbols.split(",") if s.strip()}
        universe = [u for u in universe if u.symbol.upper() in wanted]
        if not universe:
            return f"no universe symbols matched: {sorted(wanted)}"

    btc_df = price_loader("BTC-USD")
    eth_df = price_loader("ETH-USD")

    lines: list[str] = []
    lines.append("Crypto signal diagnose")
    lines.append("=" * 60)
    lines.append(_parquet_freshness())
    lines.append(f"thresholds: STRONG>={cfg.crypto.scoring.thresholds.strong} "
                 f"WATCH>={cfg.crypto.scoring.thresholds.watchlist} "
                 f"AVOID<{cfg.crypto.scoring.thresholds.avoid}")
    lines.append("")

    for entry in universe:
        sym = entry.symbol
        price_df = price_loader(sym)
        funding_history = funding_loader(sym)
        oi_data = oi_loader(sym) or {}
        onchain = onchain_loader(sym) or {}

        ctx = SignalContext(
            symbol=sym,
            price_df=price_df,
            btc_price_df=btc_df,
            eth_price_df=eth_df,
            funding_rate=funding_history[-1] if funding_history else None,
            funding_rate_history=funding_history,
            open_interest_today=oi_data.get("open_interest_today"),
            open_interest_7d_ago=oi_data.get("open_interest_7d_ago"),
            active_addresses_z=onchain.get("active_addresses_z"),
            exchange_netflow_usd_7d=onchain.get("exchange_netflow_usd_7d"),
        )
        signals = evaluate_all(ctx)

        cand = build_candidate(
            cfg=cfg,
            symbol=sym,
            signals=signals,
            annualised_vol=_annualised_vol(price_df),
            drawdown_30d=_drawdown_30d(price_df),
        )

        lines.append(sym)
        for name, sig in signals.items():
            explainer = _EXPLAINERS.get(name)
            text = explainer(sig) if explainer else f"strength={sig.strength:+.2f} -> {sig.label}"
            lines.append(f"  {name}: {text}")
        lines.append(f"  score: {cand.score:.2f} -> {cand.action}")
        lines.append("")

    return "\n".join(lines)


__all__ = ["run_diagnose"]
