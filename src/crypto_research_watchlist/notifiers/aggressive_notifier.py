"""Telegram notifier for the aggressive rotation engine.

Long-form message: each candidate gets action emoji + symbol + score +
BUY zone + take-profit targets + stop loss + notable signals as bullets.
ATR-based target math is reused from the existing telegram.py renderer.
"""

from __future__ import annotations

import html
import logging
import os
from typing import Any

from ..autotrader.aggressive import (
    AggressiveAction,
    AggressiveDecision,
    AggressiveReport,
)

logger = logging.getLogger(__name__)


_ACTION_PRIORITY: dict[AggressiveAction, tuple[int, str]] = {
    AggressiveAction.ROTATE:        (0, "🔄"),
    AggressiveAction.BUY:           (0, "🟢"),
    AggressiveAction.DO_NOT_CHASE:  (1, "🚫"),
    AggressiveAction.COOLDOWN_HOLD: (2, "⏳"),
    AggressiveAction.HOLD:          (3, "⏸"),
    AggressiveAction.AVOID:         (4, "🔴"),
    AggressiveAction.NO_CANDIDATES: (5, "⚠"),
}

_ACTIONABLE = {
    AggressiveAction.BUY,
    AggressiveAction.ROTATE,
    AggressiveAction.DO_NOT_CHASE,
}


def _esc(s: str) -> str:
    return html.escape(str(s), quote=False)


def _fmt_price(p: float | None) -> str:
    if p is None:
        return "?"
    if p >= 1000:
        return f"{p:,.0f}"
    if p >= 1:
        return f"{p:,.2f}"
    return f"{p:.4f}"


def _fmt_pct(p: float | None) -> str:
    if p is None:
        return ""
    arrow = "↑" if p > 0 else "↓" if p < 0 else "="
    return f"{arrow}{abs(p) * 100:.1f}%"


def _atr_zones(px: dict | None) -> dict | None:
    """Compute buy zone, take-profit ladder, stop loss from extras['px'].

    Mirrors the math in notifiers/telegram.py:
      buy = [last - atr, last - 0.3*atr]
      tp1 = last + atr
      tp2 = last + 2 * atr
      stop = last - 1.5 * atr
    """
    if not px:
        return None
    last = px.get("last")
    atr = px.get("atr14")
    if last is None or atr is None or atr <= 0:
        return None
    return {
        "buy_lo": last - atr,
        "buy_hi": last - 0.3 * atr,
        "tp1": last + atr,
        "tp2": last + 2 * atr,
        "stop": last - 1.5 * atr,
        "last": last,
    }


def _candidate_block(
    d: AggressiveDecision,
    candidate: Any | None,
) -> str:
    _, emoji = _ACTION_PRIORITY.get(d.action, (99, "•"))
    score_pct = int(round(((d.score or 0.0) + 1) * 50))
    header = (
        f"{emoji} <b>{_esc(d.action.value)}</b> "
        f"{_esc(d.symbol)}  score={score_pct}/100"
    )
    if d.action == AggressiveAction.ROTATE and d.rotate_from_symbol:
        header += f"  (from {_esc(d.rotate_from_symbol)})"

    lines = [header]
    for r in d.reasons[:4]:
        lines.append(f"  · {_esc(r)}")

    px = None
    if candidate is not None:
        extras = getattr(candidate, "extras", {}) or {}
        px = extras.get("px")
        last_pct1d = px.get("p1d") if px else None
        last_pct7d = px.get("p7d") if px else None
        if px and px.get("last") is not None:
            lines.append(
                f"  📈 ${_fmt_price(px['last'])}  "
                f"1d {_fmt_pct(last_pct1d)}  7d {_fmt_pct(last_pct7d)}"
            )

    zones = _atr_zones(px)
    if zones is not None:
        lines.append(
            f"  🎯 buy <code>${_fmt_price(zones['buy_lo'])} - "
            f"${_fmt_price(zones['buy_hi'])}</code>"
        )
        lines.append(
            f"  ✅ tp <code>${_fmt_price(zones['tp1'])}</code> / "
            f"<code>${_fmt_price(zones['tp2'])}</code>"
        )
        lines.append(f"  🛑 stop <code>${_fmt_price(zones['stop'])}</code>")

    if candidate is not None:
        signals = getattr(candidate, "signals", {}) or {}
        notable = sorted(
            (s for s in signals.values() if getattr(s, "is_notable", False)),
            key=lambda x: -abs(getattr(x, "strength", 0.0)),
        )[:2]
        for s in notable:
            arrow = "🟢" if getattr(s, "strength", 0) > 0 else "🔴"
            bullet = (s.bullets[0] if getattr(s, "bullets", None) else s.label)
            lines.append(
                f"  {arrow} <b>{_esc(s.source)}</b>: {_esc(bullet)}"
            )

    return "\n".join(lines)


def format_report(report: AggressiveReport, run_result: Any | None = None) -> str:
    """Render an AggressiveReport as Telegram HTML.

    Quiet by default: returns "" if no actionable decisions.
    """
    if not report.decisions:
        return ""
    actionable = [d for d in report.decisions if d.action in _ACTIONABLE]
    if not actionable and not report.notes:
        return ""

    cand_by_symbol: dict[str, Any] = {}
    if run_result is not None:
        for c in getattr(run_result, "candidates", []) or []:
            sym = (getattr(c, "symbol", "") or "").upper()
            if sym:
                cand_by_symbol[sym] = c

    header = (
        f"⚡ <b>CRYPTO AGGRESSIVE ROTATION</b> | "
        f"{len(report.decisions)} decision(s)"
    )
    ordered = sorted(
        report.decisions,
        key=lambda d: _ACTION_PRIORITY.get(d.action, (99, ""))[0],
    )
    blocks = [
        _candidate_block(d, cand_by_symbol.get(d.symbol))
        for d in ordered
        if d.action in _ACTIONABLE or d.action == AggressiveAction.HOLD
    ]
    if not blocks:
        blocks = [_candidate_block(d, cand_by_symbol.get(d.symbol)) for d in ordered]

    notes_block = ""
    if report.notes:
        notes_block = "\n\n<i>Notes:</i>\n" + "\n".join(
            f"  · {_esc(n)}" for n in report.notes[:6]
        )

    full = header + "\n\n" + "\n\n".join(blocks) + notes_block
    if len(full) > 4000:
        full = full[:4000] + "\n\n<i>...truncated</i>"
    return full


def send_aggressive_telegram(
    report: AggressiveReport, run_result: Any | None = None, *, http=None,
) -> bool:
    text = format_report(report, run_result)
    if not text:
        logger.info("aggressive-notifier: empty — skipping send")
        return False
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    enabled_raw = os.environ.get("TELEGRAM_ENABLED", "true").lower()
    if enabled_raw in ("false", "0", "no"):
        logger.info(
            "aggressive-notifier: TELEGRAM_ENABLED=%s — skipping", enabled_raw,
        )
        return False
    if not (token and chat_id):
        logger.warning(
            "aggressive-notifier: missing creds (token_set=%s chat_id_set=%s)",
            bool(token), bool(chat_id),
        )
        return False
    try:
        if http is None:
            import httpx
            http = httpx
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        resp = http.post(
            url,
            json={
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
            timeout=15.0,
        )
        resp.raise_for_status()
        logger.info("aggressive-notifier: Telegram POST ok (%d chars)", len(text))
        return True
    except Exception as exc:
        logger.warning("aggressive-notifier: send failed: %s", exc)
        return False
