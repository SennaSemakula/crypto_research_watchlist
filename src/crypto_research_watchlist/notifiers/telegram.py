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


_ACTION_EMOJI = {
    "STRONG": "🟢",
    "WATCH": "🟡",
    "AVOID": "🔴",
    "INSUFFICIENT_DATA": "⚪",
}


def _fmt_price(p: float | None) -> str:
    if p is None:
        return "?"
    if p >= 1000:
        return f"{p:,.0f}"
    if p >= 1:
        return f"{p:,.2f}"
    return f"{p:.4f}"


def _fmt_pct(p: float | None, label: str) -> str:
    if p is None:
        return ""
    arrow = "↑" if p > 0 else "↓" if p < 0 else "="
    return f"{label}{arrow}{abs(p) * 100:.1f}%"


def _render_candidate(idx: int, c) -> list[str]:
    out: list[str] = []
    emoji = _ACTION_EMOJI.get(c.action, "•")
    # Score is 0-100 post 2026-05 migration. Older fixtures using [-1, +1]
    # are auto-detected and rescaled.
    raw = float(c.score or 0.0)
    if -1.5 <= raw <= 1.5:
        raw = (raw + 1.0) * 50.0
    score_pct = int(round(max(0.0, min(100.0, raw))))
    px = (c.extras.get("px") or {}) if c.extras else {}

    header_parts = [f"{emoji} <b>{idx}. {_escape(c.symbol)}</b> [{c.action}] · {score_pct}/100"]
    if px.get("last") is not None:
        moves = []
        if px.get("p1d") is not None:
            moves.append(_fmt_pct(px["p1d"], "1d "))
        if px.get("p7d") is not None:
            moves.append(_fmt_pct(px["p7d"], "7d "))
        suffix = "  ".join([f"${_fmt_price(px['last'])}"] + moves)
        header_parts.append(suffix)
    out.append("  ·  ".join(header_parts))

    notable = sorted(
        (s for s in c.signals.values() if s.is_notable),
        key=lambda x: -abs(x.strength),
    )[:3]
    for s in notable:
        arrow = "🟢" if s.strength > 0 else "🔴"
        bullet = s.bullets[0] if s.bullets else _escape(s.label)
        out.append(f"    {arrow} <b>{_escape(s.source)}</b>: {_escape(bullet)}")

    last = px.get("last")
    atr = px.get("atr14")
    if last is not None and atr is not None and atr > 0:
        buy_lo = last - atr
        buy_hi = last - 0.3 * atr
        sell1 = last + atr
        sell2 = last + 2 * atr
        stop = last - 1.5 * atr
        out.append(f"    🎯 buy <code>${_fmt_price(buy_lo)} - ${_fmt_price(buy_hi)}</code>")
        out.append(f"    ✅ tp <code>${_fmt_price(sell1)}</code> / <code>${_fmt_price(sell2)}</code>")
        out.append(f"    🛑 stop <code>${_fmt_price(stop)}</code>")

    if c.risk and c.risk.warnings:
        for w in c.risk.warnings[:2]:
            out.append(f"    ⚠️ {_escape(w)}")
    if c.risk and c.risk.time_horizon and c.risk.time_horizon != "n/a":
        out.append(f"    ⏱ horizon {_escape(c.risk.time_horizon)} · max weight {c.risk.max_portfolio_weight:.0%}")

    return out


def _render_html(result: RunResult) -> str:
    lines: list[str] = []
    date_str = result.run_at.strftime("%Y-%m-%d")
    lines.append(f"📊 <b>Crypto Daily Watchlist</b>  {date_str}")
    lines.append("")

    market = result.market or {}
    btc = market.get("btc") or {}
    eth = market.get("eth") or {}
    if btc.get("last") or eth.get("last"):
        lines.append("<b>Market</b>")
        if btc.get("last") is not None:
            lines.append(
                f"  BTC ${_fmt_price(btc['last'])}  "
                f"{_fmt_pct(btc.get('p1d'), '1d ')}  {_fmt_pct(btc.get('p7d'), '7d ')}"
            )
        if eth.get("last") is not None:
            lines.append(
                f"  ETH ${_fmt_price(eth['last'])}  "
                f"{_fmt_pct(eth.get('p1d'), '1d ')}  {_fmt_pct(eth.get('p7d'), '7d ')}"
            )
        if btc.get("last") and eth.get("last"):
            lines.append(f"  ETH/BTC {eth['last'] / btc['last']:.4f}")
        lines.append("")

    top = result.candidates[:5]
    if top:
        lines.append(f"<b>Ranked candidates</b>  (top {len(top)} of {len(result.candidates)})")
        lines.append("")
        for idx, c in enumerate(top, 1):
            lines.extend(_render_candidate(idx, c))
            lines.append("")

    if result.candidates:
        actions = {}
        for c in result.candidates:
            actions[c.action] = actions.get(c.action, 0) + 1
        action_summary = " · ".join(f"{k}: {v}" for k, v in sorted(actions.items()))
        lines.append(f"<i>{len(result.universe)} symbols · {action_summary}</i>")
    lines.append(f"<i>Run {result.run_at.isoformat(timespec='minutes')}</i>")
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
