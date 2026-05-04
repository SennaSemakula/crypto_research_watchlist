"""End-to-end pipeline: load -> signals -> candidates -> persist.

Pure-ish: takes injected providers so tests can run offline. The default
``run_once`` factory wires the parquet historical data as the spot price
provider, which makes development entirely offline.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd
from sqlalchemy.engine import Engine

from .candidates import Candidate, build_candidate, rank_candidates
from .config import AppConfig
from .data.coingecko_provider import CoinGeckoProvider, MarketSummary
from .db import session_factory, session_scope
from .decisions import attach_decisions
from .models import CandidateRecord, SignalRecord
from .signals import SignalContext, evaluate_all
from .universe import UniverseEntry, build_universe, filter_universe

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PARQUET = REPO_ROOT / "data" / "historical" / "prices_daily.parquet"


PriceLoader = Callable[[str], pd.DataFrame | None]


@dataclass(slots=True)
class RunResult:
    run_at: datetime
    candidates: list[Candidate] = field(default_factory=list)
    universe: list[UniverseEntry] = field(default_factory=list)
    report_path: Path | None = None
    market: dict = field(default_factory=dict)


def parquet_price_loader(parquet_path: Path = DEFAULT_PARQUET) -> PriceLoader:
    """Returns a loader that pulls a per-symbol DataFrame from the daily parquet."""
    if not parquet_path.exists():
        # Make this an empty loader that returns None for everything; tests may
        # inject their own.
        def _missing(_symbol: str) -> pd.DataFrame | None:
            return None
        return _missing
    cached = pd.read_parquet(parquet_path)
    cached["date"] = pd.to_datetime(cached["date"])

    def _load(symbol: str) -> pd.DataFrame | None:
        df = cached[cached.symbol == symbol]
        if df.empty:
            return None
        return df.copy()

    return _load


def _annualised_vol(price_df: pd.DataFrame | None, window: int = 30) -> float | None:
    if price_df is None or price_df.empty or len(price_df) < window + 1:
        return None
    close = price_df.sort_values("date")["close"].astype(float)
    daily_ret = close.pct_change().dropna().tail(window)
    if daily_ret.empty or daily_ret.std() == 0:
        return None
    return float(daily_ret.std() * np.sqrt(365))


def _drawdown_30d(price_df: pd.DataFrame | None) -> float | None:
    if price_df is None or price_df.empty or len(price_df) < 31:
        return None
    close = price_df.sort_values("date")["close"].astype(float).tail(31)
    peak = close.cummax()
    return float(close.iloc[-1] / peak.max() - 1.0)


def _price_extras(price_df: pd.DataFrame | None) -> dict | None:
    """Compact price metadata used by the renderer (last, %1d/%7d/%30d, ATR-14, 30d high/low)."""
    if price_df is None or price_df.empty:
        return None
    df = price_df.sort_values("date")
    closes = df["close"].astype(float).to_numpy()
    if len(closes) < 1:
        return None
    last = float(closes[-1])
    out: dict = {"last": last}
    if len(closes) >= 2:
        out["p1d"] = float(last / closes[-2] - 1.0)
    if len(closes) >= 6:
        out["p5d"] = float(last / closes[-6] - 1.0)
    if len(closes) >= 8:
        out["p7d"] = float(last / closes[-8] - 1.0)
    if len(closes) >= 31:
        out["p30d"] = float(last / closes[-31] - 1.0)
    if len(df) >= 30 and {"high", "low"}.issubset(df.columns):
        recent = df.tail(30)
        out["high30"] = float(recent["high"].astype(float).max())
        out["low30"] = float(recent["low"].astype(float).min())
    if len(df) >= 60 and {"high", "low"}.issubset(df.columns):
        recent = df.tail(60)
        out["high60"] = float(recent["high"].astype(float).max())
        out["low60"] = float(recent["low"].astype(float).min())
    if len(df) >= 15 and {"high", "low", "close"}.issubset(df.columns):
        recent = df.tail(15)
        h = recent["high"].astype(float).to_numpy()
        lo = recent["low"].astype(float).to_numpy()
        c = recent["close"].astype(float).to_numpy()
        prev_c = np.concatenate(([c[0]], c[:-1]))
        tr = np.maximum.reduce([h - lo, np.abs(h - prev_c), np.abs(lo - prev_c)])
        out["atr14"] = float(tr[-14:].mean())
    return out


def _default_market_loader() -> MarketSummary | None:
    """Production market summary loader: reads CoinGecko key from env.

    Returns None on absent key, HTTP failure, or any provider exception.
    Pipeline never crashes when this fails.
    """
    try:
        import os
        key = os.environ.get("COINGECKO_API_KEY") or None
        if not key:
            return None
        return CoinGeckoProvider(api_key=key).fetch_market_summary()
    except Exception as exc:
        logger.warning("default market summary loader failed: %s", exc)
        return None


def run_once(
    *,
    cfg: AppConfig,
    engine: Engine | None = None,
    price_loader: PriceLoader | None = None,
    funding_loader: Callable[[str], list[float]] | None = None,
    oi_loader: Callable[[str], dict] | None = None,
    onchain_loader: Callable[[str], dict] | None = None,
    market_loader: Callable[[], MarketSummary | None] | None = None,
    write_report: bool = True,
    refresh_news: bool = True,
) -> RunResult:
    """One pipeline run.

    Builds the filtered universe, fetches per-symbol data, runs every
    signal evaluator, builds candidates with risk verdicts, persists to
    the DB (if engine is provided), and writes a markdown report.

    ``oi_loader`` is split out from the older ``onchain_loader`` so callers
    can wire OI separately. For backward compatibility, when oi_loader is
    None and the legacy onchain_loader returns a dict containing
    ``open_interest_today``, those keys are still consumed here.
    """
    run_at = datetime.now(UTC)
    price_loader = price_loader or parquet_price_loader()

    # News refresh is best-effort: failure logs WARNING, run continues.
    if refresh_news and engine is not None:
        try:
            from .news.orchestrator import refresh_news as _refresh_news
            _refresh_news(engine, cfg.crypto)
        except Exception as exc:
            logger.warning("news refresh failed: %s", exc)

    universe = filter_universe(cfg, build_universe(cfg))
    btc_df = price_loader("BTC-USD")
    eth_df = price_loader("ETH-USD")

    candidates: list[Candidate] = []
    for entry in universe:
        price_df = price_loader(entry.symbol)
        funding_history = funding_loader(entry.symbol) if funding_loader else None
        oi_data = oi_loader(entry.symbol) if oi_loader else {}
        onchain = onchain_loader(entry.symbol) if onchain_loader else {}

        # Allow legacy onchain_loader to also carry OI keys until callers
        # migrate. New callers should use oi_loader.
        oi_today = (
            (oi_data or {}).get("open_interest_today")
            or (onchain or {}).get("open_interest_today")
        )
        oi_7d = (
            (oi_data or {}).get("open_interest_7d_ago")
            or (onchain or {}).get("open_interest_7d_ago")
        )

        ctx = SignalContext(
            symbol=entry.symbol,
            price_df=price_df,
            btc_price_df=btc_df,
            eth_price_df=eth_df,
            funding_rate=funding_history[-1] if funding_history else None,
            funding_rate_history=funding_history,
            open_interest_today=oi_today,
            open_interest_7d_ago=oi_7d,
            active_addresses_z=onchain.get("active_addresses_z") if onchain else None,
            exchange_netflow_usd_7d=onchain.get("exchange_netflow_usd_7d") if onchain else None,
        )
        signals = evaluate_all(ctx)
        c = build_candidate(
            cfg=cfg,
            symbol=entry.symbol,
            signals=signals,
            annualised_vol=_annualised_vol(price_df),
            drawdown_30d=_drawdown_30d(price_df),
        )
        px = _price_extras(price_df)
        if px:
            c.extras["px"] = px
        if oi_today is not None:
            c.extras["oi_today"] = oi_today
        if oi_7d is not None:
            c.extras["oi_7d_ago"] = oi_7d
        candidates.append(c)

    ranked = rank_candidates(candidates)

    # Per-symbol 24h news for the decision engine (graceful no-op when
    # the engine is unavailable or the lookup raises).
    news_by_symbol: dict[str, list] = {}
    if engine is not None:
        try:
            from .news.lookup import recent_articles_for
            for c in ranked:
                articles = recent_articles_for(engine, c.symbol, hours=24, limit=5)
                if articles:
                    news_by_symbol[c.symbol.split("-")[0].upper()] = articles
        except Exception as exc:
            logger.warning("news lookup for decisions failed: %s", exc)

    try:
        attach_decisions(ranked, news_by_symbol=news_by_symbol)
    except Exception as exc:
        logger.warning("attach_decisions failed: %s", exc)

    # Market summary is fail-safe: absent key, network error, or loader
    # exception all collapse to None. The renderer treats None as "skip
    # the line".
    summary: MarketSummary | None = None
    if market_loader is not None:
        try:
            summary = market_loader()
        except Exception as exc:
            logger.warning("market_loader raised; continuing without summary: %s", exc)
            summary = None

    market = {
        "btc": _price_extras(btc_df),
        "eth": _price_extras(eth_df),
        "summary": summary,
    }

    if engine is not None:
        _persist(engine, run_at, ranked)

    report_path: Path | None = None
    if write_report:
        report_path = _write_report(cfg, run_at, ranked)

    return RunResult(
        run_at=run_at,
        candidates=ranked,
        universe=universe,
        report_path=report_path,
        market=market,
    )


def _persist(engine: Engine, run_at: datetime, candidates: list[Candidate]) -> None:
    SessionLocal = session_factory(engine)
    with session_scope(SessionLocal) as session:
        for c in candidates:
            for src, sig in c.signals.items():
                session.add(SignalRecord(
                    run_at=run_at,
                    symbol=c.symbol,
                    source=src,
                    strength=float(sig.strength),
                    label=sig.label,
                    details=sig.details,
                ))
            session.add(CandidateRecord(
                run_at=run_at,
                symbol=c.symbol,
                action=c.action,
                score=float(c.score),
                reason=c.reason,
                payload={
                    "signals": {k: {"label": v.label, "strength": v.strength} for k, v in c.signals.items()},
                    "risk": _verdict_dict(c.risk),
                },
            ))


def _verdict_dict(verdict) -> dict | None:
    if verdict is None:
        return None
    return {
        "action_label": verdict.action_label,
        "max_portfolio_weight": verdict.max_portfolio_weight,
        "warnings": verdict.warnings,
        "invalidation_conditions": verdict.invalidation_conditions,
        "time_horizon": verdict.time_horizon,
    }


def _write_report(cfg: AppConfig, run_at: datetime, candidates: list[Candidate]) -> Path:
    reports_dir = REPO_ROOT / cfg.reports.reports_dir
    reports_dir.mkdir(parents=True, exist_ok=True)
    path = reports_dir / f"watchlist_{run_at.date().isoformat()}.md"

    lines: list[str] = []
    lines.append("# Crypto Watchlist")
    lines.append("")
    lines.append(f"_Generated {run_at.isoformat()}_")
    lines.append("")
    lines.append("Decision support, not advice. No live trades.")
    lines.append("")
    lines.append("| Rank | Symbol | Action | Score | Reason |")
    lines.append("|---|---|---|---|---|")
    for idx, c in enumerate(candidates[: cfg.reports.top_n_terminal], start=1):
        reason = c.reason.replace("|", "\\|")
        lines.append(f"| {idx} | {c.symbol} | {c.action} | {c.score:+.2f} | {reason} |")
    lines.append("")
    lines.append("## Notable signals")
    lines.append("")
    for c in candidates:
        if not c.notable_signals:
            continue
        lines.append(f"### {c.symbol} ({c.action}, score {c.score:+.2f})")
        for s in c.notable_signals:
            tag = "+" if s.direction == "bull" else "-" if s.direction == "bear" else "."
            lines.append(f"- [{tag}] **{s.source}** ({s.label})")
            for b in s.bullets:
                lines.append(f"    - {b}")
        if c.risk and c.risk.warnings:
            lines.append("- Risk warnings:")
            for w in c.risk.warnings:
                lines.append(f"    - {w}")
        lines.append("")

    # Also dump the JSON snapshot for downstream tooling.
    snapshot = {
        "run_at": run_at.isoformat(),
        "candidates": [
            {
                "symbol": c.symbol,
                "score": c.score,
                "action": c.action,
                "reason": c.reason,
                "signals": {k: {"label": v.label, "strength": v.strength, "bullets": v.bullets} for k, v in c.signals.items()},
            }
            for c in candidates
        ],
    }
    (reports_dir / f"watchlist_{run_at.date().isoformat()}.json").write_text(json.dumps(snapshot, indent=2, default=str))

    path.write_text("\n".join(lines))
    return path
