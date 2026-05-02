"""Aggressive rotation gate, ported from stock_research_watchlist and adapted for crypto.

Differences from the stock version:
  - No earnings blackout (crypto has no earnings).
  - chase-trap default lifted from 15% (5d) to 30% (5d) because crypto is fatter-tailed.
  - Adds a 1d spike guard on top of the 5d test (single-session rips are common in crypto).
  - Funding-rate awareness is a TODO; the API stub is here for the daily calibration
    routine to flesh out without breaking callers.

Public API (mirrors the stock repo so cross-system tooling can stay generic):
  classify(symbol, panel, cfg) -> Decision
    - panel: dict of recent return windows: {"r1d": ..., "r5d": ..., "r60d": ..., "vol_annual": ...}
    - cfg: AggressiveConfig
    - returns Decision(action, reason)

  rotate_decision(holding, candidate, holding_signals, candidate_signals, cfg) -> RotateDecision
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .config import AggressiveConfig

Action = Literal["STRONG", "WATCH", "AVOID"]


@dataclass
class Decision:
    action: Action
    reason: str


@dataclass
class RotateDecision:
    rotate: bool
    reason: str


def is_chase_trap(panel: dict, cfg: AggressiveConfig) -> tuple[bool, str]:
    """Return (tripped, reason). Only the 5d and 1d gates apply; 60d momentum is the
    *signal*, not a gate."""
    r5d = panel.get("r5d")
    r1d = panel.get("r1d")
    if r5d is not None and abs(r5d) >= cfg.chase_trap_5d_pct:
        return True, f"5d {r5d:+.1%} >= {cfg.chase_trap_5d_pct:.0%}"
    if r1d is not None and abs(r1d) >= cfg.chase_trap_1d_pct:
        return True, f"1d {r1d:+.1%} >= {cfg.chase_trap_1d_pct:.0%}"
    return False, ""


def classify(symbol: str, panel: dict, cfg: AggressiveConfig) -> Decision:
    """STRONG / WATCH / AVOID decision for one symbol from its return panel."""
    tripped, reason = is_chase_trap(panel, cfg)
    if tripped:
        return Decision("AVOID", f"chase-trap: {reason}")

    r60 = panel.get("r60d")
    if r60 is None:
        return Decision("WATCH", "insufficient history (no 60d)")

    if r60 >= 0.20:
        return Decision("STRONG", f"60d momentum {r60:+.1%}")
    if r60 >= 0.05:
        return Decision("WATCH", f"60d momentum {r60:+.1%}")
    return Decision("AVOID", f"60d momentum {r60:+.1%} below 5%")


def rotate_decision(
    holding: str,
    candidate: str,
    holding_signals: dict,
    candidate_signals: dict,
    cfg: AggressiveConfig,
) -> RotateDecision:
    """Decide whether to rotate from `holding` to `candidate`.

    Mirrors the stock repo's logic:
      - rotate if holding is in chase-trap (forced exit), OR
      - rotate if candidate's score - holding's score >= rotation_score_gap, OR
      - rotate if holding's rank has slipped by >= rotation_rank_drop spots since entry.
    """
    if holding == candidate:
        return RotateDecision(False, "candidate == holding")

    tripped, reason = is_chase_trap(holding_signals, cfg)
    if tripped:
        return RotateDecision(True, f"holding {holding} chase-trap: {reason}")

    h_score = holding_signals.get("score")
    c_score = candidate_signals.get("score")
    if h_score is not None and c_score is not None:
        if (c_score - h_score) >= cfg.rotation_score_gap:
            return RotateDecision(True, f"score gap {c_score - h_score:.1f} >= {cfg.rotation_score_gap}")

    h_rank_now = holding_signals.get("rank_now")
    h_rank_at_entry = holding_signals.get("rank_at_entry")
    if h_rank_now is not None and h_rank_at_entry is not None:
        slip = h_rank_now - h_rank_at_entry
        if slip >= cfg.rotation_rank_drop:
            return RotateDecision(True, f"rank slipped {slip} spots from entry")

    return RotateDecision(False, "no rotation trigger")


# ---------------------------------------------------------------------------
# Funding-rate awareness — placeholder for the calibration agent to wire.
# ---------------------------------------------------------------------------

def funding_signal(symbol: str) -> float | None:
    """Return a funding-rate-derived score in [-1, +1], or None if unavailable.

    TODO: source via ccxt fetch_funding_rate() against a public endpoint
    (e.g. binance, bybit). For now returns None so callers fall back gracefully.
    Overheated funding (>0.1% per 8h) is bearish for the underlying; deeply
    negative funding is bullish (capitulation).
    """
    return None
