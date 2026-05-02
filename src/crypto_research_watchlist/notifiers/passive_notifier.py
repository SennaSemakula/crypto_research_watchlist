"""Telegram notifier for passive accumulation runs.

Mirrors the stock side's passive_notifier:
  - Quiet by default (empty string when no actionable decisions).
  - Header: CRYPTO AUTO-INVESTOR [SHADOW] | N decisions
  - One block per decision with action emoji, symbol, score, tranche, reasons.
  - Truncate at 4000 chars (Telegram cap is 4096).

Sends directly via httpx using TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID env vars.
"""

from __future__ import annotations

import html
import logging
import os

from ..autotrader.passive import PassiveAction, PassiveDecision, PassiveReport

logger = logging.getLogger(__name__)


_ACTION_PRIORITY: dict[PassiveAction, tuple[int, str]] = {
    PassiveAction.AUTO_BUY_FIRST_TRANCHE: (0, "✅"),
    PassiveAction.AUTO_ADD_TRANCHE:       (0, "➕"),
    PassiveAction.AUTO_BUY_SHADOW:        (1, "👁"),
    PassiveAction.BLOCK_BUY_RISK_EVENT:   (2, "⛔"),
    PassiveAction.WAIT_FOR_BETTER_PRICE:  (3, "⏸"),
    PassiveAction.HOLD:                   (4, "🔒"),
    PassiveAction.SELL_REVIEW_ONLY:       (2, "⚠"),
    PassiveAction.DO_NOT_BUY:             (5, "❌"),
}

_ACTIONABLE = {
    PassiveAction.AUTO_BUY_FIRST_TRANCHE,
    PassiveAction.AUTO_ADD_TRANCHE,
    PassiveAction.AUTO_BUY_SHADOW,
    PassiveAction.BLOCK_BUY_RISK_EVENT,
    PassiveAction.SELL_REVIEW_ONLY,
}


def _esc(s: str) -> str:
    return html.escape(str(s), quote=False)


def _format_decision(d: PassiveDecision) -> str:
    _, emoji = _ACTION_PRIORITY.get(d.action, (99, "•"))
    size = f" ${d.tranche_usd:.2f}" if d.tranche_usd else ""
    hc = " (high-conv)" if d.high_conviction else ""
    header = (
        f"{emoji} <b>{_esc(d.action.value)}</b> {_esc(d.symbol)}  "
        f"score={d.accumulation_score:+.2f}{size}{hc}"
    )
    if not d.reasons:
        return header
    body = "\n".join(f"  · {_esc(r)}" for r in d.reasons)
    return f"{header}\n{body}"


def format_report(report: PassiveReport, *, daily_mode: bool = False) -> str:
    """Render a PassiveReport as a Telegram-ready HTML message.

    Behaviour:
    - daily_mode=False (legacy): returns empty string when no decision is
      actionable, so the cron-driven shadow run can stay quiet.
    - daily_mode=True: ALWAYS returns a formatted message. When no buys
      are actionable today the message explains why concisely
      ("0 buys today: top 3 candidates X/Y/Z below buy floor; revisit if
      any drops Z%").
    """
    has_actionable = any(d.action in _ACTIONABLE for d in report.decisions)
    if not daily_mode:
        if not report.decisions and not report.notes:
            return ""
        if not has_actionable and not report.notes:
            return ""

    mode_tag = "[SHADOW]" if report.shadow_mode else "[LIVE]"
    header = (
        f"🤖 <b>CRYPTO AUTO-INVESTOR {mode_tag}</b> | "
        f"{len(report.decisions)} decision(s)"
    )

    if daily_mode and not has_actionable:
        # Friendly never-quiet summary.
        # Sort decisions by score descending and surface top 3 names + scores.
        ranked = sorted(
            report.decisions,
            key=lambda d: -float(d.accumulation_score or 0.0),
        )[:3]
        names = ", ".join(
            f"{_esc(d.symbol)} ({float(d.accumulation_score or 0.0):.1f})"
            for d in ranked
        ) or "-"
        explainer = (
            f"0 buys today: top candidates {names} below buy floor. "
            f"Revisit when score crosses the threshold or a deeper dip prints."
        )
        body = explainer
        notes = ""
        if report.notes:
            notes = "\n\n<i>Notes:</i>\n" + "\n".join(
                f"   · {_esc(n)}" for n in report.notes[:5]
            )
        return f"{header}\n\n{body}{notes}"

    ordered = sorted(
        report.decisions,
        key=lambda d: _ACTION_PRIORITY.get(d.action, (99, ""))[0],
    )
    body_blocks = [_format_decision(d) for d in ordered]

    notes_block = ""
    if report.notes:
        notes_block = "\n\n<i>Notes:</i>\n" + "\n".join(
            f"  · {_esc(n)}" for n in report.notes[:10]
        )

    full = header + "\n\n" + "\n\n".join(body_blocks) + notes_block
    if len(full) > 4000:
        full = full[:4000] + "\n\n<i>...truncated</i>"
    return full


def send_passive_telegram(report: PassiveReport, *, http=None, daily_mode: bool = False) -> bool:
    """Post a formatted passive report via the Telegram Bot API.

    ``daily_mode=True`` forces a never-quiet send (the daily cron always
    wants a message). ``daily_mode=False`` preserves the older quiet-by-
    default semantics (used by intraday cron checks).

    Returns True on success, False otherwise. Never raises.
    """
    text = format_report(report, daily_mode=daily_mode)
    if not text:
        logger.info("passive-notifier: empty report — skipping send")
        return False

    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    enabled_raw = os.environ.get("TELEGRAM_ENABLED", "true").lower()
    if enabled_raw in ("false", "0", "no"):
        logger.info("passive-notifier: TELEGRAM_ENABLED=%s — skipping", enabled_raw)
        return False
    if not (token and chat_id):
        logger.warning(
            "passive-notifier: missing creds (token_set=%s chat_id_set=%s)",
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
        logger.info("passive-notifier: Telegram POST ok (%d chars)", len(text))
        return True
    except Exception as exc:
        logger.warning("passive-notifier: Telegram send failed: %s", exc)
        return False
