"""Passive accumulation engine, crypto-tuned.

Mirrors the stock side's passive.py shape (PassiveAction enum, PassiveDecision,
PassiveReport, evaluate / run_once functions) with crypto-specific gates:

  - Universe is the 10-name crypto list.
  - Sizing is in USD (no FX layer).
  - Buy-the-dip: -8% from 30d high while score is still WATCH or better
    (crypto is fatter-tailed than equities, so the dip threshold is wider
    than the stock side's -5%).
  - Weekly cap: $300/symbol, $1500/total per ISO week. Tunable.
  - Risk gates: stablecoin de-peg flag (cross_asset signal), and 30d
    portfolio drawdown <= -15% halts new buys.
  - 24/7 markets: no market-hours gate.
  - No earnings logic at all.
  - Shadow-only in v1 (paper-only repo). evaluate() is a pure function so
    test runs are fully offline; run_once_passive logs decisions to the DB.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class PassiveAction(str, Enum):  # noqa: UP042 - str(member) format must stay "PassiveAction.AUTO_BUY", not "AUTO_BUY"
    AUTO_BUY_FIRST_TRANCHE = "AUTO_BUY_FIRST_TRANCHE"
    AUTO_ADD_TRANCHE = "AUTO_ADD_TRANCHE"
    AUTO_BUY_SHADOW = "AUTO_BUY_SHADOW"
    WAIT_FOR_BETTER_PRICE = "WAIT_FOR_BETTER_PRICE"
    HOLD = "HOLD"
    BLOCK_BUY_RISK_EVENT = "BLOCK_BUY_RISK_EVENT"
    SELL_REVIEW_ONLY = "SELL_REVIEW_ONLY"
    DO_NOT_BUY = "DO_NOT_BUY"


@dataclass(slots=True)
class PassiveDecision:
    action: PassiveAction
    symbol: str
    tranche_usd: float | None
    quantity: float | None
    accumulation_score: float
    high_conviction: bool
    reasons: list[str] = field(default_factory=list)


@dataclass(slots=True)
class PassiveReport:
    decisions: list[PassiveDecision] = field(default_factory=list)
    errors: int = 0
    shadow_mode: bool = True
    notes: list[str] = field(default_factory=list)

    @property
    def buys_placed(self) -> int:
        return sum(
            1 for d in self.decisions
            if d.action == PassiveAction.AUTO_BUY_FIRST_TRANCHE
        )

    @property
    def add_tranches_placed(self) -> int:
        return sum(
            1 for d in self.decisions
            if d.action == PassiveAction.AUTO_ADD_TRANCHE
        )

    @property
    def shadow_buys(self) -> int:
        return sum(
            1 for d in self.decisions
            if d.action == PassiveAction.AUTO_BUY_SHADOW
        )

    @property
    def blocked(self) -> int:
        return sum(
            1 for d in self.decisions
            if d.action == PassiveAction.BLOCK_BUY_RISK_EVENT
        )


@dataclass(slots=True, frozen=True)
class PassiveContext:
    """Pre-computed state for evaluate(). Built by build_passive_context.

    All fields are crypto-flavoured: no FX, no market-hours, no earnings.
    """

    cash_usd: float
    positions_by_symbol_usd: dict[str, float]
    open_position_count: int
    wtd_buys_total_usd: float
    wtd_buys_per_symbol_usd: dict[str, float]
    portfolio_drawdown_30d: float | None
    stablecoin_depeg_flag: bool
    px_extras_by_symbol: dict[str, dict[str, Any]]
    last_tranche_date_by_symbol: dict[str, datetime | None] = field(default_factory=dict)


def _iso_week_start(now: datetime | None = None) -> datetime:
    now = now or datetime.now(UTC)
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    monday = now - timedelta(days=now.weekday())
    return datetime(monday.year, monday.month, monday.day, tzinfo=UTC)


def build_passive_context(
    *,
    run_result: Any,
    paper_cash_usd: float,
    positions_by_symbol_usd: dict[str, float],
    wtd_buys_total_usd: float = 0.0,
    wtd_buys_per_symbol_usd: dict[str, float] | None = None,
    last_tranche_date_by_symbol: dict[str, datetime | None] | None = None,
    portfolio_drawdown_30d: float | None = None,
) -> PassiveContext:
    """Assemble a PassiveContext from a pipeline RunResult and paper state.

    The cross_asset signal carries stablecoin de-peg detection (handled in
    signals/cross_asset.py). We sniff for it here so evaluate() doesn't
    need to know about signal internals.
    """
    px_extras: dict[str, dict[str, Any]] = {}
    depeg_flag = False
    for c in getattr(run_result, "candidates", []) or []:
        sym = (getattr(c, "symbol", "") or "").upper()
        if not sym:
            continue
        extras = getattr(c, "extras", {}) or {}
        if "px" in extras:
            px_extras[sym] = extras["px"]
        signals = getattr(c, "signals", {}) or {}
        cross = signals.get("cross_asset") if isinstance(signals, dict) else None
        if cross is not None:
            details = getattr(cross, "details", {}) or {}
            if details.get("stablecoin_depeg"):
                depeg_flag = True

    return PassiveContext(
        cash_usd=float(paper_cash_usd or 0.0),
        positions_by_symbol_usd=dict(positions_by_symbol_usd or {}),
        open_position_count=sum(
            1 for v in (positions_by_symbol_usd or {}).values() if v > 0
        ),
        wtd_buys_total_usd=float(wtd_buys_total_usd or 0.0),
        wtd_buys_per_symbol_usd=dict(wtd_buys_per_symbol_usd or {}),
        portfolio_drawdown_30d=portfolio_drawdown_30d,
        stablecoin_depeg_flag=depeg_flag,
        px_extras_by_symbol=px_extras,
        last_tranche_date_by_symbol=dict(last_tranche_date_by_symbol or {}),
    )


def _dip_from_30d_high(px: dict | None) -> float | None:
    """Return the negative pct drop from the 30d high, e.g. -0.10 means -10%.

    None when extras don't carry both ``last`` and ``high30``.
    """
    if not px:
        return None
    last = px.get("last")
    high = px.get("high30")
    if last is None or high is None or high <= 0:
        return None
    return float(last) / float(high) - 1.0


def evaluate(
    *,
    cfg,
    run_result: Any,
    ctx: PassiveContext,
) -> PassiveReport:
    """Pure-function evaluator. No I/O, no DB writes. Suitable for unit tests.

    For each candidate emits one PassiveDecision. Order of decisions in the
    report follows the input candidate ranking.
    """
    pcfg = cfg.passive if hasattr(cfg, "passive") else cfg
    report = PassiveReport(shadow_mode=bool(pcfg.shadow_mode))

    # Hard portfolio-level gates first: emit one BLOCK note then keep
    # evaluating per-symbol (each will return BLOCK_BUY_RISK_EVENT) so the
    # operator gets the per-symbol audit trail.
    portfolio_blocked = False
    portfolio_block_reason = ""
    if ctx.stablecoin_depeg_flag:
        portfolio_blocked = True
        portfolio_block_reason = "stablecoin de-peg flag set (cross_asset signal)"
    if (
        ctx.portfolio_drawdown_30d is not None
        and ctx.portfolio_drawdown_30d <= -abs(pcfg.drawdown_gate_pct)
    ):
        portfolio_blocked = True
        portfolio_block_reason = (
            f"portfolio drawdown {ctx.portfolio_drawdown_30d * 100:.1f}% "
            f"<= -{abs(pcfg.drawdown_gate_pct) * 100:.1f}% gate"
        )
    if portfolio_blocked:
        report.notes.append(f"portfolio gate tripped: {portfolio_block_reason}")

    candidates = getattr(run_result, "candidates", []) or []

    for c in candidates:
        symbol = (getattr(c, "symbol", "") or "").upper()
        if not symbol:
            continue
        score_raw = float(getattr(c, "score", 0.0) or 0.0)
        # Auto-detect legacy [-1, +1] scoring (older fixtures, calibration
        # back-tests) and rescale to 0-100 to match config thresholds.
        score = score_raw if score_raw > 1.5 or score_raw < -1.5 else (score_raw + 1.0) * 50.0
        # Floor / cap.
        score = max(0.0, min(100.0, score))
        action_label = getattr(c, "action", "") or ""

        if portfolio_blocked:
            report.decisions.append(_decision(
                action=PassiveAction.BLOCK_BUY_RISK_EVENT,
                symbol=symbol, score=score,
                reasons=[portfolio_block_reason],
            ))
            continue

        # Universe check: not strictly required (the pipeline already filters)
        # but mirrors the stock side's defence-in-depth.
        allowed = {s.upper() for s in cfg.universe.symbols}
        if symbol not in allowed:
            report.decisions.append(_decision(
                action=PassiveAction.DO_NOT_BUY, symbol=symbol, score=score,
                reasons=[f"{symbol} not in configured universe"],
            ))
            continue

        if action_label == "AVOID" or score < pcfg.min_accumulation_score:
            report.decisions.append(_decision(
                action=PassiveAction.DO_NOT_BUY, symbol=symbol, score=score,
                reasons=[
                    f"score {score:.1f}/100 or action {action_label or '-'} "
                    f"below floor {pcfg.min_accumulation_score:.1f}",
                ],
            ))
            continue

        px = ctx.px_extras_by_symbol.get(symbol)
        last_price = px.get("last") if px else None
        dip = _dip_from_30d_high(px)

        # Buy-the-dip eligibility: dip <= -threshold (e.g. -8% drop). If we
        # have no dip data, fail-open as WAIT (we don't auto-buy on missing
        # data, mirroring stock-side fail-closed behaviour).
        dip_qualified = dip is not None and dip <= -abs(pcfg.dip_threshold_from_30d_high_pct)

        if not dip_qualified:
            dip_str = f"{dip * 100:+.1f}%" if dip is not None else "n/a"
            report.decisions.append(_decision(
                action=PassiveAction.WAIT_FOR_BETTER_PRICE,
                symbol=symbol, score=score,
                reasons=[
                    f"dip from 30d high {dip_str} > "
                    f"-{abs(pcfg.dip_threshold_from_30d_high_pct) * 100:.1f}% threshold",
                ],
            ))
            continue

        # Caps: weekly per-symbol, weekly total, single-name allocation.
        wtd_sym = ctx.wtd_buys_per_symbol_usd.get(symbol, 0.0)
        wtd_total = ctx.wtd_buys_total_usd

        already_held_usd = ctx.positions_by_symbol_usd.get(symbol, 0.0)
        is_add = already_held_usd > 0
        target_tranche = pcfg.add_tranche_usd if is_add else pcfg.first_tranche_usd

        per_sym_remaining = max(0.0, pcfg.weekly_cap_per_symbol_usd - wtd_sym)
        total_remaining = max(0.0, pcfg.weekly_cap_total_usd - wtd_total)
        cash_remaining = max(0.0, ctx.cash_usd)

        sized = min(target_tranche, per_sym_remaining, total_remaining, cash_remaining)
        if sized <= 0.01:
            report.decisions.append(_decision(
                action=PassiveAction.WAIT_FOR_BETTER_PRICE,
                symbol=symbol, score=score,
                reasons=[
                    f"weekly cap or cash exhausted: per-sym remaining "
                    f"${per_sym_remaining:.2f}, total ${total_remaining:.2f}, "
                    f"cash ${cash_remaining:.2f}",
                ],
            ))
            continue

        high_conv = score >= pcfg.high_conviction_score_threshold
        # Compute quantity at last_price; if last is missing, leave as None so
        # downstream can decide. We fail-closed if we can't size.
        qty: float | None = None
        if last_price and last_price > 0:
            qty = round(sized / float(last_price), 8)
        else:
            report.decisions.append(_decision(
                action=PassiveAction.DO_NOT_BUY, symbol=symbol, score=score,
                reasons=["last price missing — cannot size tranche"],
            ))
            continue

        action = (
            PassiveAction.AUTO_ADD_TRANCHE if is_add
            else PassiveAction.AUTO_BUY_FIRST_TRANCHE
        )
        reasons = [
            f"score {score:.1f}/100 >= floor {pcfg.min_accumulation_score:.1f}"
            + (" (high-conviction)" if high_conv else ""),
            f"dip from 30d high {dip * 100:+.1f}% <= "
            f"-{abs(pcfg.dip_threshold_from_30d_high_pct) * 100:.1f}% threshold",
            f"tranche ${sized:.2f}{' (add)' if is_add else ''}",
        ]

        # Shadow rebrand. Keep original action label in the reasons for analytics.
        if pcfg.shadow_mode:
            reasons.append(f"SHADOW: order not placed (would-be {action.value})")
            action = PassiveAction.AUTO_BUY_SHADOW

        report.decisions.append(_decision(
            action=action, symbol=symbol, score=score,
            tranche_usd=sized, quantity=qty,
            high_conviction=high_conv, reasons=reasons,
        ))

    return report


def _decision(
    *, action: PassiveAction, symbol: str, score: float,
    reasons: list[str], tranche_usd: float | None = None,
    quantity: float | None = None, high_conviction: bool = False,
) -> PassiveDecision:
    return PassiveDecision(
        action=action, symbol=symbol,
        tranche_usd=tranche_usd, quantity=quantity,
        accumulation_score=score, high_conviction=high_conviction,
        reasons=reasons,
    )


# ---- Persistence -----------------------------------------------------------

def persist_decisions(engine, run_at: datetime, report: PassiveReport) -> int:
    """Append PassiveDecision rows for an audit trail. Returns row count."""
    if engine is None or not report.decisions:
        return 0
    from sqlalchemy.orm import Session

    from ..models import PassiveDecision as PassiveDecisionRow

    written = 0
    with Session(engine) as s:
        for d in report.decisions:
            s.add(PassiveDecisionRow(
                run_at=run_at, symbol=d.symbol, action=d.action.value,
                accumulation_score=float(d.accumulation_score or 0.0),
                tranche_usd=float(d.tranche_usd) if d.tranche_usd is not None else None,
                reasons={"reasons": list(d.reasons), "high_conviction": d.high_conviction},
                shadow_mode=1 if report.shadow_mode else 0,
            ))
            written += 1
        s.commit()
    return written


# ---- Orchestration ---------------------------------------------------------

def _wtd_from_db(engine, now: datetime | None = None) -> tuple[float, dict[str, float]]:
    """Sum tranche_usd of PassiveDecision rows logged since Monday 00:00 UTC.

    Counts only AUTO_BUY_* actions. Shadow buys count too because the
    weekly cap is the operator's INTENT to deploy capital, not the realised
    fills (paper / shadow has no real fills).
    """
    from sqlalchemy.orm import Session

    from ..models import PassiveDecision as PassiveDecisionRow

    week_start = _iso_week_start(now)
    actions = {
        PassiveAction.AUTO_BUY_FIRST_TRANCHE.value,
        PassiveAction.AUTO_ADD_TRANCHE.value,
        PassiveAction.AUTO_BUY_SHADOW.value,
    }
    total = 0.0
    per_sym: dict[str, float] = {}
    with Session(engine) as s:
        rows = s.query(PassiveDecisionRow).filter(
            PassiveDecisionRow.run_at >= week_start,
        ).all()
    for r in rows:
        if r.action not in actions or r.tranche_usd is None:
            continue
        total += float(r.tranche_usd or 0.0)
        per_sym[r.symbol] = per_sym.get(r.symbol, 0.0) + float(r.tranche_usd or 0.0)
    return total, per_sym


def _portfolio_drawdown_30d(run_result: Any) -> float | None:
    """Approximate portfolio drawdown via BTC's 30d drawdown when available.

    Crypto positions tend to be highly correlated to BTC over a 30d window,
    so BTC drawdown is a reasonable proxy for the paper portfolio's
    drawdown without needing to track equity curves day by day. If BTC
    has no extras, returns None and the gate fails open.
    """
    market = getattr(run_result, "market", {}) or {}
    btc = market.get("btc") or {}
    last = btc.get("last")
    high = btc.get("high30")
    if last is None or high is None or high <= 0:
        return None
    return float(last) / float(high) - 1.0


def run_once_passive(
    *, engine, cfg, run_result: Any, broker=None, run_at: datetime | None = None,
) -> PassiveReport:
    """Orchestrator. Builds context, evaluates, persists, returns report.

    No order placement (shadow only in v1). The broker (PaperBroker) is
    optional and used purely to read cash + positions when present. When
    absent, defaults to the cfg portfolio total + no positions, which is
    appropriate for fresh-DB / first-run evaluations.
    """
    run_at = run_at or datetime.now(UTC)

    cash_usd = float(cfg.portfolio.cash_available_usd)
    positions_usd: dict[str, float] = {}
    last_tranche: dict[str, datetime | None] = {}
    if broker is not None:
        try:
            cash_usd = float(broker.get_cash() or 0.0)
        except Exception as exc:
            logger.warning("paper broker get_cash failed: %s", exc)
        try:
            for p in broker.get_positions():
                if not p.symbol or p.quantity <= 0:
                    continue
                # We mark positions in USD using last avg price; the
                # supervisor reconciles vs current market separately.
                positions_usd[p.symbol.upper()] = float(p.avg_price * p.quantity)
        except Exception as exc:
            logger.warning("paper broker get_positions failed: %s", exc)

    wtd_total, wtd_per_sym = (0.0, {})
    if engine is not None:
        try:
            wtd_total, wtd_per_sym = _wtd_from_db(engine, run_at)
        except Exception as exc:
            logger.warning("WTD DB read failed: %s", exc)

    ctx = build_passive_context(
        run_result=run_result,
        paper_cash_usd=cash_usd,
        positions_by_symbol_usd=positions_usd,
        wtd_buys_total_usd=wtd_total,
        wtd_buys_per_symbol_usd=wtd_per_sym,
        last_tranche_date_by_symbol=last_tranche,
        portfolio_drawdown_30d=_portfolio_drawdown_30d(run_result),
    )

    report = evaluate(cfg=cfg, run_result=run_result, ctx=ctx)

    if engine is not None:
        try:
            persist_decisions(engine, run_at, report)
        except Exception as exc:
            logger.warning("persist_decisions failed: %s", exc)
            report.errors += 1

    return report
