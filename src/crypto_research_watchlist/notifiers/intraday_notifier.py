"""Intraday alert notifier — compact Telegram message.

This is an alert (not a digest). Fires only when material change is detected
by the intraday scan. Two possible sections:

  - Score moves: candidates whose 0-100 score moved beyond the delta
    threshold since the prior snapshot, or whose action label flipped.
  - New high-impact news: articles published in the last N minutes whose
    sentiment magnitude clears 0.5.

If only one section has content, render only that section. Always include
header + footer. Truncate at 3800 chars (Telegram cap is 4096).
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Iterable

from .telegram import _chunk, _escape

logger = logging.getLogger(__name__)

_MAX_CHARS = 3800
_ACTION_EMOJI = {
    "STRONG": "STRONG",
    "WATCH": "WATCH",
    "AVOID": "AVOID",
    "INSUFFICIENT_DATA": "n/a",
}


@dataclass(slots=True)
class ScoreMove:
    symbol: str
    prior_score: float
    current_score: float
    prior_action: str | None
    current_action: str

    @property
    def delta(self) -> float:
        return self.current_score - self.prior_score


@dataclass(slots=True)
class NewsHit:
    symbol: str
    title: str
    sentiment_score: float
    sentiment_label: str


@dataclass(slots=True)
class IntradayAlert:
    """Materialised set of changes that justify firing an alert."""

    score_moves: list[ScoreMove] = field(default_factory=list)
    news_hits: list[NewsHit] = field(default_factory=list)
    scanned_symbols: int = 0
    now: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def has_signal(self) -> bool:
        return bool(self.score_moves or self.news_hits)


def _render_score_line(m: ScoreMove) -> str:
    delta = m.delta
    sign = "+" if delta >= 0 else ""
    prior = int(round(m.prior_score))
    curr = int(round(m.current_score))
    action_part = _escape(m.current_action)
    if m.prior_action and m.prior_action != m.current_action:
        action_part = (
            f"{_escape(m.prior_action)} -&gt; {_escape(m.current_action)}"
        )
    return (
        f"  {_escape(m.symbol)}: {prior} -&gt; {curr} "
        f"{action_part} ({sign}{delta:.0f})"
    )


def _sentiment_dot(label: str, score: float) -> str:
    if score >= 0.5:
        return "+"
    if score <= -0.5:
        return "-"
    return "."


def _render_news_line(n: NewsHit) -> str:
    sign = "+" if n.sentiment_score >= 0 else ""
    dot = _sentiment_dot(n.sentiment_label, n.sentiment_score)
    title = _escape(n.title[:140])
    return (
        f"  [{dot}] {_escape(n.symbol)}: {title} "
        f"({sign}{n.sentiment_score:.2f})"
    )


def render_alert(alert: IntradayAlert) -> str:
    """Render an IntradayAlert as Telegram HTML.

    Returns "" when there's no signal — callers should not POST in that case.
    """
    if not alert.has_signal():
        return ""

    hhmm = alert.now.strftime("%H:%M UTC")
    lines: list[str] = [f"<b>Intraday alert</b>  {hhmm}", ""]

    if alert.score_moves:
        lines.append("<b>Score moves</b>")
        for m in alert.score_moves:
            lines.append(_render_score_line(m))
        lines.append("")

    if alert.news_hits:
        lines.append("<b>New high-impact news</b>")
        for n in alert.news_hits:
            lines.append(_render_news_line(n))
        lines.append("")

    lines.append(f"<i>(scanned {alert.scanned_symbols} symbols)</i>")

    text = "\n".join(lines)
    if len(text) > _MAX_CHARS:
        text = text[:_MAX_CHARS] + "\n<i>...truncated</i>"
    return text


def send_intraday_telegram(alert: IntradayAlert, *, http=None) -> bool:
    """POST the alert to Telegram. Returns True on success.

    Returns False (and logs INFO) when there's no signal, no creds, or
    TELEGRAM_ENABLED is off.
    """
    text = render_alert(alert)
    if not text:
        logger.info("intraday-notifier: no signal — skipping send")
        return False

    enabled_raw = os.environ.get("TELEGRAM_ENABLED", "true").lower()
    if enabled_raw in ("false", "0", "no"):
        logger.info("intraday-notifier: TELEGRAM_ENABLED=%s — skipping", enabled_raw)
        return False

    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not (token and chat_id):
        logger.warning(
            "intraday-notifier: missing creds (token_set=%s chat_id_set=%s)",
            bool(token), bool(chat_id),
        )
        return False

    chunks = _chunk(text, limit=_MAX_CHARS)
    if http is None:
        import httpx
        http = httpx
    try:
        for idx, chunk in enumerate(chunks, 1):
            prefix = f"<b>(part {idx}/{len(chunks)})</b>\n" if len(chunks) > 1 else ""
            url = f"https://api.telegram.org/bot{token}/sendMessage"
            resp = http.post(
                url,
                json={
                    "chat_id": chat_id,
                    "text": prefix + chunk,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": True,
                },
                timeout=15.0,
            )
            resp.raise_for_status()
        logger.info("intraday-notifier: Telegram POST ok (%d chars)", len(text))
        return True
    except Exception as exc:
        logger.warning("intraday-notifier: send failed: %s", exc)
        return False


__all__ = [
    "IntradayAlert",
    "NewsHit",
    "ScoreMove",
    "render_alert",
    "send_intraday_telegram",
]
