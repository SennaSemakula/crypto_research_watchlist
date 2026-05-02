"""Telegram bot notifier — off by default.

Renders a compact ranking block from RunResult and posts it via
``sendMessage``. HTML escaping mirrors the stock side. Setup: see
README under "Notifications".
"""

from __future__ import annotations

import logging
from typing import Protocol

from ..config import AppConfig, EnvSettings
from ..pipeline import RunResult
from .base import NotificationOutcome

logger = logging.getLogger(__name__)

_MAX_PER_MESSAGE_CHARS = 3800


class _HTTPClient(Protocol):
    def post(self, url, *args, **kwargs): ...


class TelegramNotifier:
    name = "telegram"
    API_BASE = "https://api.telegram.org"

    def __init__(self, cfg: AppConfig, env: EnvSettings, http: _HTTPClient | None = None) -> None:
        self._cfg = cfg
        self._env = env
        self._http = http

    def enabled(self) -> bool:
        return bool(
            self._cfg.notifications.telegram
            and self._env.telegram_enabled
            and self._env.telegram_bot_token
            and self._env.telegram_chat_id
        )

    def send(self, result: RunResult) -> NotificationOutcome:
        if not self.enabled():
            return NotificationOutcome(self.name, "disabled")

        body_html = _render_html(result)
        chunks = _chunk(body_html, limit=_MAX_PER_MESSAGE_CHARS)

        http = self._http or _make_httpx()
        sent = 0
        last_err: str | None = None
        for idx, chunk in enumerate(chunks, 1):
            prefix = f"<b>(part {idx}/{len(chunks)})</b>\n" if len(chunks) > 1 else ""
            try:
                self._post(http, prefix + chunk)
                sent += 1
            except Exception as exc:
                last_err = f"chunk {idx}/{len(chunks)}: {exc}"
                logger.warning("Telegram notifier failed %s", last_err)
                break

        if sent == 0:
            return NotificationOutcome(self.name, "failed", last_err)
        if sent < len(chunks):
            return NotificationOutcome(self.name, "partial", last_err)
        return NotificationOutcome(self.name, "sent")

    def _post(self, http, body: str) -> None:
        url = f"{self.API_BASE}/bot{self._env.telegram_bot_token}/sendMessage"
        payload = {
            "chat_id": self._env.telegram_chat_id,
            "text": body,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        resp = http.post(url, json=payload, timeout=15.0)
        resp.raise_for_status()


def _escape(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _render_html(result: RunResult) -> str:
    lines: list[str] = []
    lines.append(f"<b>Crypto Watchlist</b> {result.run_at.isoformat(timespec='minutes')}")
    lines.append("")
    for idx, c in enumerate(result.candidates[:5], start=1):
        lines.append(
            f"{idx}. <b>{_escape(c.symbol)}</b> "
            f"<i>{_escape(c.action)}</i> ({c.score:+.2f}) — {_escape(c.reason)}"
        )
    return "\n".join(lines)


def _chunk(text: str, *, limit: int) -> list[str]:
    if len(text) <= limit:
        return [text]
    out: list[str] = []
    cur: list[str] = []
    cur_len = 0
    for line in text.splitlines(keepends=True):
        if cur_len + len(line) > limit:
            out.append("".join(cur))
            cur = [line]
            cur_len = len(line)
        else:
            cur.append(line)
            cur_len += len(line)
    if cur:
        out.append("".join(cur))
    return out


def _make_httpx():
    import httpx  # type: ignore[import-not-found]
    return httpx.Client()
