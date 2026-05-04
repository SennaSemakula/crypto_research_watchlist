"""Order supervisor — reconciles paper-broker state with system state.

Crypto sibling of the stock side's order_supervisor. Differences:
  * No real broker integration: only the paper broker is in scope.
  * No protective STOP/TARGET orders to manage (paper-only, shadow-only).
  * Focus is on detecting drift between decisions logged in the
    passive_decisions / aggressive_decisions tables and the actual
    PaperPosition / PaperCash rows.

Run cadence: any frequency. The function is idempotent — it never places
orders, only reads state and emits warnings.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class SupervisorReport:
    reconciled: int = 0
    mismatches: int = 0
    warnings: list[str] = field(default_factory=list)
    cash_usd: float = 0.0
    positions_count: int = 0


def reconcile(*, engine, broker, lookback_hours: int = 48) -> SupervisorReport:
    """Compare recent decisions to current paper portfolio state.

    Two checks:
      a) Recent AUTO_BUY_FIRST_TRANCHE / AUTO_ADD_TRANCHE that were NOT
         shadow_mode but have no corresponding paper position. (In v1
         this should never fire because shadow_mode=true is the default,
         but the check is here so that when live mode flips on later,
         drift is caught immediately.)
      b) Open paper positions for which there is NO decision audit trail
         in the lookback window.

    All findings go into report.warnings. report.mismatches counts each
    distinct issue.
    """
    from sqlalchemy import select
    from sqlalchemy.orm import Session

    from ..models import (
        AggressiveDecision as AggressiveDecisionRow,
    )
    from ..models import (
        PaperCash,
        PaperPosition,
    )
    from ..models import (
        PassiveDecision as PassiveDecisionRow,
    )

    report = SupervisorReport()
    cutoff = datetime.now(UTC) - timedelta(hours=lookback_hours)

    # --- Read paper portfolio first.
    cash = 0.0
    positions: list[PaperPosition] = []
    if broker is not None:
        try:
            cash = float(broker.get_cash() or 0.0)
        except Exception as exc:
            logger.warning("supervisor: broker get_cash failed: %s", exc)
            report.warnings.append(f"broker.get_cash failed: {exc}")
        try:
            positions = list(broker.get_positions() or [])
        except Exception as exc:
            logger.warning("supervisor: broker get_positions failed: %s", exc)
            report.warnings.append(f"broker.get_positions failed: {exc}")
    else:
        # Fallback to direct DB read.
        with Session(engine) as s:
            row = s.get(PaperCash, 1)
            if row is not None:
                cash = float(row.cash_usd or 0.0)
            positions = list(s.scalars(select(PaperPosition)).all())

    held = {p.symbol.upper(): p for p in positions if p.quantity > 0}
    report.cash_usd = cash
    report.positions_count = len(held)

    # --- Pull decisions in the lookback window.
    with Session(engine) as s:
        passive_rows = s.query(PassiveDecisionRow).filter(
            PassiveDecisionRow.run_at >= cutoff,
        ).all()
        aggressive_rows = s.query(AggressiveDecisionRow).filter(
            AggressiveDecisionRow.run_at >= cutoff,
        ).all()

    decisions_by_symbol: dict[str, list[Any]] = {}
    for r in passive_rows:
        decisions_by_symbol.setdefault(r.symbol.upper(), []).append(r)
    for r in aggressive_rows:
        decisions_by_symbol.setdefault(r.symbol.upper(), []).append(r)

    # Check (a): non-shadow buy decisions without a matching position.
    buy_actions = {
        "AUTO_BUY_FIRST_TRANCHE",
        "AUTO_ADD_TRANCHE",
        "BUY",
        "ROTATE",
    }
    for r in passive_rows + aggressive_rows:
        action = getattr(r, "action", "")
        if action not in buy_actions:
            continue
        if isinstance(r, PassiveDecisionRow) and r.shadow_mode:
            continue
        sym = r.symbol.upper()
        report.reconciled += 1
        if sym not in held:
            report.mismatches += 1
            report.warnings.append(
                f"{sym}: decision {action} on "
                f"{r.run_at.isoformat() if r.run_at else '?'} "
                f"but no paper position exists"
            )

    # Check (b): open positions with no decision audit trail.
    for sym, p in held.items():
        if sym not in decisions_by_symbol:
            report.mismatches += 1
            report.warnings.append(
                f"{sym}: paper position {p.quantity:.6f} @ ${p.avg_price:.2f} "
                f"has no decision audit in last {lookback_hours}h"
            )

    return report


def format_supervisor_message(report: SupervisorReport) -> str:
    """Telegram-format the warnings only. Empty string when clean."""
    if not report.warnings:
        return ""
    lines = [
        f"🛠 <b>CRYPTO SUPERVISOR</b> | "
        f"{report.mismatches} mismatch(es) "
        f"(cash ${report.cash_usd:,.2f}, {report.positions_count} positions)",
        "",
    ]
    for w in report.warnings[:20]:
        lines.append(f"  · {w}")
    return "\n".join(lines)
