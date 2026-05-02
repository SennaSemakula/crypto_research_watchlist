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
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from sqlalchemy.engine import Engine

from .candidates import Candidate, build_candidate, rank_candidates
from .config import AppConfig
from .db import session_factory, session_scope
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
    return float((close.iloc[-1] / peak.max() - 1.0))


def run_once(
    *,
    cfg: AppConfig,
    engine: Engine | None = None,
    price_loader: PriceLoader | None = None,
    funding_loader: Callable[[str], list[float]] | None = None,
    onchain_loader: Callable[[str], dict] | None = None,
    write_report: bool = True,
) -> RunResult:
    """One pipeline run.

    Builds the filtered universe, fetches per-symbol data, runs every
    signal evaluator, builds candidates with risk verdicts, persists to
    the DB (if engine is provided), and writes a markdown report.
    """
    run_at = datetime.now(timezone.utc)
    price_loader = price_loader or parquet_price_loader()

    universe = filter_universe(cfg, build_universe(cfg))
    btc_df = price_loader("BTC-USD")
    eth_df = price_loader("ETH-USD")

    candidates: list[Candidate] = []
    for entry in universe:
        price_df = price_loader(entry.symbol)
        funding_history = funding_loader(entry.symbol) if funding_loader else None
        onchain = onchain_loader(entry.symbol) if onchain_loader else {}

        ctx = SignalContext(
            symbol=entry.symbol,
            price_df=price_df,
            btc_price_df=btc_df,
            eth_price_df=eth_df,
            funding_rate=funding_history[-1] if funding_history else None,
            funding_rate_history=funding_history,
            open_interest_today=onchain.get("open_interest_today") if onchain else None,
            open_interest_7d_ago=onchain.get("open_interest_7d_ago") if onchain else None,
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
        candidates.append(c)

    ranked = rank_candidates(candidates)

    if engine is not None:
        _persist(engine, run_at, ranked)

    report_path: Path | None = None
    if write_report:
        report_path = _write_report(cfg, run_at, ranked)

    return RunResult(run_at=run_at, candidates=ranked, universe=universe, report_path=report_path)


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
