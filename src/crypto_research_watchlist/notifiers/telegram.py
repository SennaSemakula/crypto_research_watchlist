"""Telegram bot notifier — daily crypto watchlist render.

Sections:
  - Header: Crypto Daily Watchlist DATE
  - Paper portfolio block (when there is cash or positions)
  - Active catalysts: top 3 highest-magnitude news from last 24h
  - Since your last check: per-coin headline bullets
  - Ranked candidates: top 5 with rich panels
  - Footer: action breakdown + run timestamp

The render is HTML for Telegram (parse_mode=HTML). Long messages chunk
on line boundaries via ``_chunk``. Score is 0-100 (post 2026-05).
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

    def __init__(
        self,
        cfg: AppConfig,
        env: EnvSettings,
        http: _HTTPClient | None = None,
        engine=None,
    ) -> None:
        self._cfg = cfg
        self._env = env
        self._http = http
        self._engine = engine

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

        body_html = render_html(result, engine=self._engine)
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


# ---------------------------------------------------------------------------
# Render helpers
# ---------------------------------------------------------------------------


def _escape(text: str) -> str:
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


_ACTION_EMOJI = {
    "STRONG": "🟢",
    "WATCH": "🟡",
    "AVOID": "🔴",
    "INSUFFICIENT_DATA": "⚪",
}

_SENTIMENT_DOT = {"positive": "🟢", "negative": "🔴", "neutral": "⚡"}


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
    arrow = "up" if p > 0 else "dn" if p < 0 else "=="
    return f"{label}{arrow} {abs(p) * 100:.1f}%"


def _to_score_pct(raw_score: float) -> int:
    """Score is 0-100 post-migration; legacy [-1, +1] auto-rescales."""
    raw = float(raw_score or 0.0)
    if -1.5 <= raw <= 1.5:
        raw = (raw + 1.0) * 50.0
    return int(round(max(0.0, min(100.0, raw))))


# ---------------------------------------------------------------------------
# Sections
# ---------------------------------------------------------------------------


def _render_paper_portfolio(engine) -> list[str]:
    """Show the paper portfolio block (cash + positions). Hide if zero."""
    if engine is None:
        return []
    try:
        from sqlalchemy import select

        from ..db import session_factory, session_scope
        from ..models import PaperCash, PaperPosition
        SessionLocal = session_factory(engine)
        with session_scope(SessionLocal) as session:
            cash_row = session.get(PaperCash, 1)
            positions = list(session.scalars(select(PaperPosition)).all())
            cash = float(cash_row.cash_usd) if cash_row else 0.0
            holdings = [p for p in positions if (p.quantity or 0.0) > 0]
    except Exception as exc:
        logger.debug("paper portfolio render skipped: %s", exc)
        return []
    if cash == 0 and not holdings:
        return []
    lines = ["💼 <b>PAPER PORTFOLIO</b>"]
    lines.append(f"   cash: $<b>{cash:,.2f}</b>")
    if holdings:
        for p in holdings:
            qty = float(p.quantity)
            avg = float(p.avg_price)
            lines.append(
                f"   {_escape(p.symbol)}: qty={qty:.4f} avg=${_fmt_price(avg)} "
                f"realised=${float(p.realised_pnl):.2f}"
            )
    lines.append("")
    return lines


def _render_active_catalysts(engine) -> list[str]:
    if engine is None:
        return []
    try:
        from ..news.lookup import top_catalysts
        catalysts = top_catalysts(engine, hours=24, limit=3)
    except Exception as exc:
        logger.debug("catalysts render skipped: %s", exc)
        return []
    if not catalysts:
        return []
    lines = ["🎯 <b>ACTIVE CATALYSTS</b>"]
    for cat in catalysts:
        dot = _SENTIMENT_DOT.get(cat.sentiment_label, "⚡")
        currencies = ",".join(cat.currencies_json[:3]) if cat.currencies_json else "-"
        lines.append(
            f"   {dot} <b>{_escape(currencies)}</b>: {_escape(cat.title[:140])}"
        )
        lines.append(
            f"      <i>{_escape(cat.source)} · sentiment {cat.sentiment_score:+.2f}</i>"
        )
    lines.append("")
    return lines


def _render_since_last_check(engine, candidates) -> list[str]:
    if engine is None:
        return []
    try:
        from ..news.lookup import recent_articles_for
    except Exception:
        return []
    section: list[str] = []
    for c in candidates[:10]:
        try:
            arts = recent_articles_for(engine, c.symbol, hours=24, limit=1)
        except Exception:
            arts = []
        if not arts:
            continue
        a = arts[0]
        dot = _SENTIMENT_DOT.get(a.sentiment_label, "⚡")
        section.append(
            f"   {dot} <b>{_escape(c.symbol)}</b>: {_escape(a.title[:120])}"
        )
    if not section:
        return []
    return ["📰 <b>SINCE YOUR LAST CHECK</b>", *section, ""]


def _candidate_tag(c, score_pct: int) -> str:
    """Short tag per candidate (e.g. 'breaking positive', 'chase trap', 'at 60d peak')."""
    px = (c.extras.get("px") or {}) if c.extras else {}
    p7d = px.get("p7d")
    p1d = px.get("p1d")
    high30 = px.get("high30")
    last = px.get("last")
    risk = c.risk
    # Chase-trap heuristic: 5d/7d above 30%.
    if p7d is not None and p7d >= 0.30:
        return "🚫 chase trap"
    if p1d is not None and p1d >= 0.18:
        return "🚫 1d spike"
    # At 30d peak.
    if last is not None and high30 is not None and last >= 0.99 * high30 and high30 > 0:
        return "⚠️ at 30d peak"
    # Map action -> tag with directional flair.
    action = getattr(c, "action", "") or ""
    if action == "STRONG":
        return "🟢 strong setup"
    if action == "WATCH":
        return "🟡 on watch"
    if action == "AVOID":
        return "🔴 avoid"
    if action == "INSUFFICIENT_DATA":
        return "⚪ no data"
    return ""


def _candidate_fundamentals_oneliner(c) -> str | None:
    """Pick the most informative single signal bullet to surface as a fundamentals analog."""
    sigs = list((c.signals or {}).values())
    # Prefer open_interest then funding then onchain then cross_asset then technical.
    order = ["open_interest", "funding_rate", "onchain", "cross_asset", "technical"]
    for name in order:
        s = next((x for x in sigs if x.source == name), None)
        if s and s.is_notable and s.bullets:
            return s.bullets[0]
    # Fall back to any notable signal.
    notable = [s for s in sigs if s.is_notable and s.bullets]
    if notable:
        return notable[0].bullets[0]
    return None


def _render_candidate(idx: int, c, engine=None) -> list[str]:
    out: list[str] = []
    emoji = _ACTION_EMOJI.get(c.action, "•")
    score_pct = _to_score_pct(c.score)
    px = (c.extras.get("px") or {}) if c.extras else {}
    tag = _candidate_tag(c, score_pct)

    header = (
        f"{emoji} <b>{idx}. {_escape(c.symbol)}</b> "
        f"[{c.action}]  {score_pct}/100"
    )
    if tag:
        header = f"{header}  {tag}"
    out.append(header)

    if px.get("last") is not None:
        moves = []
        if px.get("p1d") is not None:
            moves.append(_fmt_pct(px["p1d"], "1d "))
        if px.get("p7d") is not None:
            moves.append(_fmt_pct(px["p7d"], "7d "))
        if px.get("p30d") is not None:
            moves.append(_fmt_pct(px["p30d"], "30d "))
        out.append(
            "   $<b>" + _fmt_price(px["last"]) + "</b>  "
            + "  ".join(moves)
        )

    # Why-wait / why-avoid line.
    why_label = (
        "Why avoid" if c.action == "AVOID"
        else "Why wait" if c.action in ("WATCH", "INSUFFICIENT_DATA")
        else "Why now"
    )
    why_text = c.reason or "no notable signals"
    out.append(f"   <i>{why_label}</i>: {_escape(why_text[:200])}")

    # Fundamentals analog.
    fa = _candidate_fundamentals_oneliner(c)
    if fa:
        out.append(f"   📊 {_escape(fa[:160])}")

    # Buy zone / TP ladder / stop loss derived from ATR-14.
    last = px.get("last")
    atr = px.get("atr14")
    if last is not None and atr is not None and atr > 0:
        buy_lo = last - atr
        buy_hi = last - 0.3 * atr
        sell1 = last + atr
        sell2 = last + 2 * atr
        stop = last - 1.5 * atr
        out.append(
            f"   🎯 buy <code>${_fmt_price(buy_lo)}-{_fmt_price(buy_hi)}</code>  "
            f"✅ tp <code>${_fmt_price(sell1)}/{_fmt_price(sell2)}</code>  "
            f"🛑 stop <code>${_fmt_price(stop)}</code>"
        )

    if c.risk and c.risk.warnings:
        for w in c.risk.warnings[:2]:
            out.append(f"   ⚠️ {_escape(w[:160])}")

    if c.risk and c.risk.time_horizon and c.risk.time_horizon != "n/a":
        out.append(
            f"   ⏱ horizon {_escape(c.risk.time_horizon)} · "
            f"max weight {c.risk.max_portfolio_weight:.0%}"
        )

    # Per-symbol news headline.
    if engine is not None:
        try:
            from ..news.lookup import recent_articles_for
            arts = recent_articles_for(engine, c.symbol, hours=24, limit=1)
            if arts:
                a = arts[0]
                dot = _SENTIMENT_DOT.get(a.sentiment_label, "⚡")
                out.append(f"   📰 {dot} {_escape(a.title[:140])}")
        except Exception:
            pass

    return out


def _render_market(market: dict | None) -> list[str]:
    if not market:
        return []
    btc = market.get("btc") or {}
    eth = market.get("eth") or {}
    if not btc.get("last") and not eth.get("last"):
        return []
    lines = ["<b>Market</b>"]
    if btc.get("last") is not None:
        lines.append(
            f"   BTC $<b>{_fmt_price(btc['last'])}</b>  "
            f"{_fmt_pct(btc.get('p1d'), '1d ')}  {_fmt_pct(btc.get('p7d'), '7d ')}"
        )
    if eth.get("last") is not None:
        lines.append(
            f"   ETH $<b>{_fmt_price(eth['last'])}</b>  "
            f"{_fmt_pct(eth.get('p1d'), '1d ')}  {_fmt_pct(eth.get('p7d'), '7d ')}"
        )
    if btc.get("last") and eth.get("last"):
        lines.append(f"   ETH/BTC {eth['last'] / btc['last']:.4f}")
    lines.append("")
    return lines


def render_html(result: RunResult, *, engine=None) -> str:
    lines: list[str] = []
    date_str = result.run_at.strftime("%Y-%m-%d")
    lines.append(f"📊 <b>Crypto Daily Watchlist</b>  {date_str}")
    lines.append("")

    # Paper portfolio.
    lines.extend(_render_paper_portfolio(engine))

    # Market context.
    lines.extend(_render_market(result.market))

    # Active catalysts.
    lines.extend(_render_active_catalysts(engine))

    # Since your last check.
    lines.extend(_render_since_last_check(engine, result.candidates))

    # Ranked candidates.
    top = result.candidates[:5]
    if top:
        lines.append(f"📊 <b>RANKED CANDIDATES</b>  (top {len(top)} of {len(result.candidates)})")
        lines.append("")
        for idx, c in enumerate(top, 1):
            lines.extend(_render_candidate(idx, c, engine=engine))
            lines.append("")

    # Footer.
    if result.candidates:
        actions = {}
        for c in result.candidates:
            actions[c.action] = actions.get(c.action, 0) + 1
        action_summary = " · ".join(f"{k}: {v}" for k, v in sorted(actions.items()))
        lines.append(f"<i>{len(result.universe)} symbols · {action_summary}</i>")
    lines.append(f"<i>Run {result.run_at.isoformat(timespec='minutes')}</i>")
    return "\n".join(lines)


# Backward-compat alias for tests that imported the underscore name.
_render_html = render_html


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
    import httpx
    return httpx.Client()
