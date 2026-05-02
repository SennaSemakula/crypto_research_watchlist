"""Paper-trading runner.

Given a list of ranked candidates and a paper broker, compute the target
position set and submit the diffs needed to converge to it. Mirrors the
stock side's runner pattern: idempotent, side-effect contained.

The runner does NOT decide what to buy: that is the candidates module's
job. The runner only converts ``[Candidate]`` into orders against the
configured portfolio.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from ..candidates import Candidate
from ..config import AppConfig
from .paper_broker import FillResult, PaperBroker

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class RunnerOutcome:
    placed: list[FillResult]
    skipped: list[tuple[str, str]]  # (symbol, reason)


def _client_order_key(symbol: str, side: str, qty: float, run_dt: datetime) -> str:
    payload = f"{run_dt.date().isoformat()}|{symbol}|{side}|{qty:.8f}"
    return "co_" + hashlib.sha1(payload.encode()).hexdigest()[:24]


def select_targets(cfg: AppConfig, ranked: list[Candidate]) -> list[Candidate]:
    target_n = cfg.portfolio.target_total_positions
    selected: list[Candidate] = []
    for c in ranked:
        if c.action != "STRONG":
            continue
        if c.score < 0.4:
            continue
        selected.append(c)
        if len(selected) >= target_n:
            break
    return selected


def run(
    cfg: AppConfig,
    broker: PaperBroker,
    quote_fn,
    ranked: list[Candidate],
    *,
    run_dt: datetime | None = None,
) -> RunnerOutcome:
    run_dt = run_dt or datetime.now(timezone.utc)
    placed: list[FillResult] = []
    skipped: list[tuple[str, str]] = []

    targets = select_targets(cfg, ranked)
    target_symbols = {c.symbol for c in targets}

    # 1) Sell anything no longer in the target set.
    for pos in broker.get_positions():
        if pos.quantity <= 0:
            continue
        if pos.symbol in target_symbols:
            continue
        qty = float(pos.quantity)
        key = _client_order_key(pos.symbol, "SELL", qty, run_dt)
        result = broker.place_market_order(
            symbol=pos.symbol, side="SELL", quantity=qty, client_order_key=key,
        )
        if result.status == "FILLED":
            placed.append(result)
        else:
            skipped.append((pos.symbol, f"sell {result.status}"))

    # 2) Buy targets we don't already hold.
    cash = broker.get_cash()
    if not targets:
        return RunnerOutcome(placed, skipped)
    per_name_cash = cash / max(len(targets), 1) * 0.99  # leave headroom for txn

    for c in targets:
        existing = broker.get_position(c.symbol)
        if existing and existing.quantity > 0:
            skipped.append((c.symbol, "already held"))
            continue
        quote = quote_fn(c.symbol)
        if quote is None or quote <= 0:
            skipped.append((c.symbol, "no quote"))
            continue
        # max_portfolio_weight from risk verdict
        max_weight = c.risk.max_portfolio_weight if c.risk else cfg.risk_limits.max_portfolio_weight_single_name
        notional = min(per_name_cash, cfg.portfolio.total_capital_usd * max_weight)
        if notional < cfg.portfolio.min_suggested_weight * cfg.portfolio.total_capital_usd:
            skipped.append((c.symbol, "notional below min suggested weight"))
            continue
        qty = notional / quote
        key = _client_order_key(c.symbol, "BUY", qty, run_dt)
        result = broker.place_market_order(
            symbol=c.symbol, side="BUY", quantity=qty, client_order_key=key,
        )
        if result.status == "FILLED":
            placed.append(result)
        else:
            skipped.append((c.symbol, f"buy {result.status}"))

    return RunnerOutcome(placed, skipped)
