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

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any, Literal

from .config import AggressiveConfig

logger = logging.getLogger(__name__)

Action = Literal["STRONG", "WATCH", "AVOID"]


@dataclass
class Decision:
    action: Action
    reason: str


@dataclass
class RotateDecision:
    rotate: bool
    reason: str


# ---------------------------------------------------------------------------
# Decision-engine layer (mirrors stock side's AggressiveAction / Decision /
# Report). The existing classify/rotate_decision helpers above remain the
# primitives; the engine layer sequences them into a per-run report.
# ---------------------------------------------------------------------------


class AggressiveAction(str, Enum):  # noqa: UP042 - str(member) format must stay "AggressiveAction.BUY", not "BUY"
    BUY = "BUY"
    HOLD = "HOLD"
    ROTATE = "ROTATE"                  # exit current holding + enter new one
    DO_NOT_CHASE = "DO_NOT_CHASE"      # chase-trap fired
    COOLDOWN_HOLD = "COOLDOWN_HOLD"    # within post chase-trap cooldown
    AVOID = "AVOID"                    # candidate fundamentally weak
    NO_CANDIDATES = "NO_CANDIDATES"


@dataclass(slots=True)
class AggressiveDecision:
    action: AggressiveAction
    symbol: str
    score: float
    prior_action: str | None = None
    rotate_from_symbol: str | None = None
    rotate_to_symbol: str | None = None
    reasons: list[str] = field(default_factory=list)


@dataclass(slots=True)
class AggressiveReport:
    decisions: list[AggressiveDecision] = field(default_factory=list)
    errors: int = 0
    notes: list[str] = field(default_factory=list)

    @property
    def buys(self) -> int:
        return sum(
            1 for d in self.decisions
            if d.action in (AggressiveAction.BUY, AggressiveAction.ROTATE)
        )

    @property
    def chase_blocks(self) -> int:
        return sum(1 for d in self.decisions if d.action == AggressiveAction.DO_NOT_CHASE)


@dataclass(slots=True)
class AggressiveContext:
    """Inputs for evaluate_aggressive. Frozen-ish snapshot from a RunResult."""

    candidates: list[Any] = field(default_factory=list)
    held_symbol: str | None = None
    held_rank_now: int | None = None
    held_rank_at_entry: int | None = None
    last_chase_trap_dates: dict[str, datetime] = field(default_factory=dict)


def _panel_for_candidate(c: Any) -> dict:
    """Extract a return panel from a Candidate's extras['px'] block.

    The pipeline writes p1d, p7d, p30d into extras["px"]. We don't have a
    5-day return field, so approximate using p7d as a conservative upper
    bound; the chase-trap gate then triggers earlier rather than later
    (intentional in crypto, where 5d != 7d but the noise is comparable).
    """
    extras = getattr(c, "extras", {}) or {}
    px = extras.get("px") or {}
    return {
        "r1d": px.get("p1d"),
        "r5d": px.get("p7d"),   # p7d as a stand-in for r5d
        "r60d": px.get("p30d"), # p30d as a stand-in for momentum lookback
    }


def _candidate_score_pct(c: Any) -> float:
    """Return the candidate score on a 0-100 scale.

    Post 2026-05 migration the candidate score is already 0-100. We still
    accept legacy [-1, +1] inputs (from old call sites or tests) by
    detecting magnitude <= 1.5 and rescaling.
    """
    raw = float(getattr(c, "score", 0.0) or 0.0)
    if -1.5 <= raw <= 1.5:
        # Looks like the legacy [-1, +1] convention.
        raw = (raw + 1.0) * 50.0
    return max(0.0, min(100.0, raw))


def build_aggressive_context(
    *,
    run_result: Any,
    held_symbol: str | None = None,
    held_rank_at_entry: int | None = None,
    last_chase_trap_dates: dict[str, datetime] | None = None,
) -> AggressiveContext:
    candidates = list(getattr(run_result, "candidates", []) or [])
    rank_now = None
    if held_symbol:
        for idx, c in enumerate(candidates, 1):
            if (getattr(c, "symbol", "") or "").upper() == held_symbol.upper():
                rank_now = idx
                break
    return AggressiveContext(
        candidates=candidates,
        held_symbol=(held_symbol.upper() if held_symbol else None),
        held_rank_now=rank_now,
        held_rank_at_entry=held_rank_at_entry,
        last_chase_trap_dates=dict(last_chase_trap_dates or {}),
    )


def evaluate_aggressive(
    *, cfg, ctx: AggressiveContext, now: datetime | None = None,
) -> AggressiveReport:
    """Per-run aggressive evaluation. Produces one AggressiveDecision per
    candidate plus rotation logic when a holding is provided.

    Pure function: no I/O. cfg may be a CryptoConfig (with .aggressive) or
    an AggressiveConfig directly.
    """
    now = now or datetime.now(UTC)
    acfg = cfg.aggressive if hasattr(cfg, "aggressive") else cfg
    cooldown_days = int(
        getattr(acfg, "cooldown_days", getattr(acfg, "cooldown_after_chase_trap_days", 3))
    )

    report = AggressiveReport()

    if not ctx.candidates:
        report.decisions.append(AggressiveDecision(
            action=AggressiveAction.NO_CANDIDATES, symbol="-", score=0.0,
            reasons=["no candidates in run_result"],
        ))
        return report

    # Score everything once. Tracks symbol -> (candidate, score_pct).
    scored: list[tuple[Any, float]] = []
    for c in ctx.candidates:
        scored.append((c, _candidate_score_pct(c)))

    # Top score candidate (drives potential rotation TO target).
    top_c, top_score_pct = max(scored, key=lambda t: t[1])

    held_score_pct: float | None = None
    held_panel: dict | None = None
    if ctx.held_symbol:
        for c, pct in scored:
            if (getattr(c, "symbol", "") or "").upper() == ctx.held_symbol:
                held_score_pct = pct
                held_panel = _panel_for_candidate(c)
                break

    for c, score_pct in scored:
        symbol = (getattr(c, "symbol", "") or "").upper()
        if not symbol:
            continue
        prior_action = getattr(c, "action", None)
        panel = _panel_for_candidate(c)
        score_raw = float(getattr(c, "score", 0.0) or 0.0)

        # Cooldown gate: if this symbol was chase-trap'd within cooldown_days,
        # skip with COOLDOWN_HOLD.
        last_trap = ctx.last_chase_trap_dates.get(symbol)
        if last_trap is not None:
            if last_trap.tzinfo is None:
                last_trap = last_trap.replace(tzinfo=UTC)
            days_since = (now - last_trap).total_seconds() / 86400.0
            if days_since < cooldown_days:
                report.decisions.append(AggressiveDecision(
                    action=AggressiveAction.COOLDOWN_HOLD, symbol=symbol,
                    score=score_raw, prior_action=str(prior_action or ""),
                    reasons=[
                        f"{symbol} within {cooldown_days}d cooldown after chase-trap "
                        f"({days_since:.1f}d ago)",
                    ],
                ))
                continue

        tripped, why = is_chase_trap(panel, acfg)
        if tripped:
            report.decisions.append(AggressiveDecision(
                action=AggressiveAction.DO_NOT_CHASE, symbol=symbol,
                score=score_raw, prior_action=str(prior_action or ""),
                reasons=[f"chase-trap: {why}"],
            ))
            continue

        # AVOID labels: pass through.
        if prior_action == "AVOID":
            report.decisions.append(AggressiveDecision(
                action=AggressiveAction.AVOID, symbol=symbol,
                score=score_raw, prior_action=str(prior_action or ""),
                reasons=[
                    f"pipeline action AVOID; "
                    f"{getattr(c, 'reason', '') or 'no notable signals'}"
                ],
            ))
            continue

        # Rotation logic — only when a holding exists and this candidate is
        # a different symbol.
        if (
            ctx.held_symbol
            and symbol != ctx.held_symbol
            and held_score_pct is not None
        ):
            score_gap = score_pct - held_score_pct
            rank_drop = None
            if ctx.held_rank_now is not None and ctx.held_rank_at_entry is not None:
                rank_drop = ctx.held_rank_now - ctx.held_rank_at_entry

            holding_chase, holding_why = is_chase_trap(held_panel or {}, acfg)
            rotate = False
            why_rot: list[str] = []
            if holding_chase:
                rotate = True
                why_rot.append(f"holding {ctx.held_symbol} chase-trap: {holding_why}")
            if score_gap >= acfg.rotation_score_gap:
                rotate = True
                why_rot.append(
                    f"score gap {score_gap:.1f} >= {acfg.rotation_score_gap:.1f}"
                )
            if rank_drop is not None and rank_drop >= acfg.rotation_rank_drop:
                rotate = True
                why_rot.append(
                    f"holding rank slipped {rank_drop} spots from entry"
                )

            if rotate and symbol == top_c.symbol.upper():
                report.decisions.append(AggressiveDecision(
                    action=AggressiveAction.ROTATE, symbol=symbol,
                    score=score_raw, prior_action=str(prior_action or ""),
                    rotate_from_symbol=ctx.held_symbol,
                    rotate_to_symbol=symbol,
                    reasons=why_rot,
                ))
                continue

        # Buy when no holding and this is the top candidate. Otherwise hold.
        if (
            not ctx.held_symbol
            and symbol == (getattr(top_c, "symbol", "") or "").upper()
            and prior_action == "STRONG"
        ):
            report.decisions.append(AggressiveDecision(
                action=AggressiveAction.BUY, symbol=symbol,
                score=score_raw, prior_action=str(prior_action or ""),
                reasons=[
                    f"top candidate (score {score_pct:.0f}/100, "
                    f"prior {prior_action})",
                ],
            ))
            continue

        report.decisions.append(AggressiveDecision(
            action=AggressiveAction.HOLD, symbol=symbol,
            score=score_raw, prior_action=str(prior_action or ""),
            reasons=[
                f"score {score_pct:.0f}/100 — no rotation trigger, no chase",
            ],
        ))

    return report


def persist_aggressive_decisions(
    engine, run_at: datetime, report: AggressiveReport,
) -> int:
    if engine is None or not report.decisions:
        return 0
    from sqlalchemy.orm import Session

    from ..models import AggressiveDecision as AggressiveDecisionRow

    written = 0
    with Session(engine) as s:
        for d in report.decisions:
            s.add(AggressiveDecisionRow(
                run_at=run_at, symbol=d.symbol, action=d.action.value,
                score=float(d.score or 0.0),
                prior_action=d.prior_action,
                reasons={
                    "reasons": list(d.reasons),
                    "rotate_from": d.rotate_from_symbol,
                    "rotate_to": d.rotate_to_symbol,
                },
            ))
            written += 1
        s.commit()
    return written


def run_once_aggressive(
    *,
    engine,
    cfg,
    run_result: Any,
    held_symbol: str | None = None,
    held_rank_at_entry: int | None = None,
    last_chase_trap_dates: dict[str, datetime] | None = None,
    run_at: datetime | None = None,
) -> AggressiveReport:
    """Build context, evaluate, persist, return report."""
    run_at = run_at or datetime.now(UTC)
    ctx = build_aggressive_context(
        run_result=run_result, held_symbol=held_symbol,
        held_rank_at_entry=held_rank_at_entry,
        last_chase_trap_dates=last_chase_trap_dates,
    )
    report = evaluate_aggressive(cfg=cfg, ctx=ctx, now=run_at)
    if engine is not None:
        try:
            persist_aggressive_decisions(engine, run_at, report)
        except Exception as exc:
            logger.warning("aggressive persist failed: %s", exc)
            report.errors += 1
    return report


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
    if (
        h_score is not None
        and c_score is not None
        and (c_score - h_score) >= cfg.rotation_score_gap
    ):
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
