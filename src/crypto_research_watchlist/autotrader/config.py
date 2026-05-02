"""Pydantic config model for the crypto rotation gate.

Mirrors the structure of the stock repo's autotrader/config.py but with
crypto-tuned defaults: higher chase-trap threshold, wider drawdown tolerance,
no earnings logic at all (crypto has no quarterly earnings).
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field


class AggressiveConfig(BaseModel):
    """The crypto rotation gate. Each field maps to one knob in config.yml."""

    chase_trap_5d_pct: float = Field(0.30, description="5d return above this = chase-trap exit/skip")
    chase_trap_1d_pct: float = Field(0.18, description="single-day spike guard (extra)")
    momentum_lookback_days: int = Field(60, description="lookback for momentum ranking")
    rotation_rank_drop: int = Field(3, description="rotate if current name's rank slips this many spots")
    rotation_score_gap: float = Field(15.0, description="rotate if challenger beats holder by this score")
    drift_floor_pt: float = Field(8.0, description="ignore drift smaller than this")
    cooldown_after_chase_trap_days: int = Field(3, description="days to wait before re-entering after a chase-trap exit")
    cooldown_days: int = Field(3, description="alias for cooldown_after_chase_trap_days, mirrors stock side wording")


class PassiveConfig(BaseModel):
    """Passive accumulation engine config. Crypto-tuned defaults."""

    shadow_mode: bool = True
    first_tranche_usd: float = 100.0
    add_tranche_usd: float = 100.0
    weekly_cap_per_symbol_usd: float = 300.0
    weekly_cap_total_usd: float = 1500.0
    dip_threshold_from_30d_high_pct: float = 0.08
    drawdown_gate_pct: float = 0.15
    min_accumulation_score: float = 0.30
    high_conviction_score_threshold: float = 0.60


class LearningSummaryConfig(BaseModel):
    weeks_back_default: int = 1


class RiskLimits(BaseModel):
    max_portfolio_weight_single_name: float = 0.30
    high_vol_threshold_annual: float = 1.20
    review_drawdown_pct: float = 0.25
    max_concurrent_positions: int = 2


class BacktestingConfig(BaseModel):
    benchmarks: list[str] = ["BTC-USD", "ETH-USD"]
    cross_asset: list[str] = ["SPY"]
    macro: list[str] = ["^VIX"]
    holding_periods_days: list[int] = [1, 7, 21, 63]
    transaction_cost_bps: int = 10
    slippage_bps: int = 8


class UniverseConfig(BaseModel):
    symbols: list[str]
    sectors: dict[str, list[str]] = {}
    exclude_stablecoins: bool = True
    exclude_meme: bool = True
    min_market_cap_usd: int = 1_000_000_000


class CryptoConfig(BaseModel):
    """Top-level config. Loaded from config.yml at the repo root."""

    universe: UniverseConfig
    aggressive: AggressiveConfig = AggressiveConfig()
    passive: PassiveConfig = PassiveConfig()
    learning_summary: LearningSummaryConfig = LearningSummaryConfig()
    risk_limits: RiskLimits = RiskLimits()
    backtesting: BacktestingConfig = BacktestingConfig()


def load_config(path: Path | str | None = None) -> CryptoConfig:
    """Load config.yml relative to the repo root, or from an explicit path."""
    if path is None:
        path = Path(__file__).resolve().parents[3] / "config.yml"
    raw = yaml.safe_load(Path(path).read_text())
    return CryptoConfig(
        universe=UniverseConfig(**raw["universe"]),
        aggressive=AggressiveConfig(**(raw.get("aggressive") or {})),
        passive=PassiveConfig(**(raw.get("passive") or {})),
        learning_summary=LearningSummaryConfig(**(raw.get("learning_summary") or {})),
        risk_limits=RiskLimits(**(raw.get("risk_limits") or {})),
        backtesting=BacktestingConfig(**(raw.get("backtesting") or {})),
    )
