"""Crypto signal evaluators.

Each evaluator is a pure function taking a SignalContext and returning a
SignalResult. The orchestrator runs every registered evaluator with
exception isolation, so one flaky source does not break the rest.

Mirrors the stock side's signals package shape so the renderer / report
templates can stay generic.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)

# Strength buckets — same convention as the stock side.
STRENGTH_NOTABLE = 0.3
STRENGTH_STRONG = 0.6


@dataclass(slots=True)
class SignalResult:
    """Single signal's verdict. ``strength`` is bounded in [-1, +1]."""

    source: str
    strength: float = 0.0
    label: str = "NEUTRAL"
    bullets: list[str] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)

    @property
    def is_notable(self) -> bool:
        return abs(self.strength) >= STRENGTH_NOTABLE

    @property
    def is_strong(self) -> bool:
        return abs(self.strength) >= STRENGTH_STRONG

    @property
    def direction(self) -> str:
        if self.strength >= STRENGTH_NOTABLE:
            return "bull"
        if self.strength <= -STRENGTH_NOTABLE:
            return "bear"
        return "neutral"


@dataclass(slots=True)
class SignalContext:
    """Bundle of inputs the evaluators may consume.

    Every field is optional so a partial context is still useful.
    Evaluators that need missing data should return a neutral SignalResult.
    """

    symbol: str
    price_df: pd.DataFrame | None = None     # OHLCV daily for this symbol
    btc_price_df: pd.DataFrame | None = None  # for cross-asset
    eth_price_df: pd.DataFrame | None = None
    funding_rate: float | None = None         # most-recent 8h funding rate
    funding_rate_history: list[float] | None = None  # last 24h, 8h cadence
    open_interest_today: float | None = None
    open_interest_7d_ago: float | None = None
    active_addresses_z: float | None = None
    exchange_netflow_usd_7d: float | None = None


def label_from_strength(s: float) -> str:
    if s >= STRENGTH_STRONG:
        return "STRONG_BULLISH"
    if s >= STRENGTH_NOTABLE:
        return "BULLISH"
    if s <= -STRENGTH_STRONG:
        return "STRONG_BEARISH"
    if s <= -STRENGTH_NOTABLE:
        return "BEARISH"
    return "NEUTRAL"


def evaluate_all(ctx: SignalContext) -> dict[str, SignalResult]:
    """Run every registered evaluator. Each is wrapped in try/except so one
    failure cannot poison the whole dict."""
    from . import cross_asset as _cross_asset
    from . import funding_rate as _funding
    from . import onchain as _onchain
    from . import open_interest as _oi
    from . import technical as _technical

    out: dict[str, SignalResult] = {}
    for name, fn in (
        ("technical", _technical.evaluate),
        ("funding_rate", _funding.evaluate),
        ("open_interest", _oi.evaluate),
        ("onchain", _onchain.evaluate),
        ("cross_asset", _cross_asset.evaluate),
    ):
        try:
            out[name] = fn(ctx)
        except Exception as exc:
            logger.debug("signal %s failed for %s: %s", name, ctx.symbol, exc)
            out[name] = SignalResult(source=name, details={"error": str(exc)})
    return out


def aggregate_strength(signals: dict[str, SignalResult], weights: dict[str, float] | None = None) -> float:
    """Weighted average of signal strengths, bounded in [-1, +1]."""
    if not signals:
        return 0.0
    weights = weights or {}
    total = 0.0
    weight_sum = 0.0
    for name, s in signals.items():
        w = float(weights.get(name, 1.0))
        total += w * s.strength
        weight_sum += w
    if weight_sum == 0:
        return 0.0
    return max(-1.0, min(1.0, total / weight_sum))
