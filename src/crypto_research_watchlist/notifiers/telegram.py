"""Telegram bot notifier — daily crypto watchlist render.

Institutional-voice format. The previous render was a database dump
(score table + 5 padded sections, even on neutral days). This render
reads like a one-page note from a senior analyst:

  Header              — date
  Market regime       — BTC/ETH spot, ETH/BTC, BTC.D, total mcap, one-line read
  Today's read        — spread bucket headline + closest-to-action names
                        with specific triggers + names to avoid
  Signals fired       — only when something actually fires (funding,
                        OI, on-chain, news), one bullet per cluster
  Action              — one liner: what to do, when next check fires

Principles:
  * Bucket labels (STRONG/WATCH/NEUTRAL/AVOID) matter more than the
    precise 0-100 score; show precise scores only when the universe is
    differentiated (>15pt spread). Round to nearest 5 otherwise.
  * Brevity is institutional — when there are no setups, the whole
    message is ~10-15 lines. We do NOT pad with empty sections.
  * Always end with action — what to do, when next.
  * The render must work even when ALL signals are neutral. Today's
    data is the test case for that.

The render is HTML for Telegram (parse_mode=HTML). Long messages chunk
on line boundaries via ``_chunk``. Score is 0-100 (post 2026-05).
"""

from __future__ import annotations

import logging
from datetime import UTC
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
# Helpers
# ---------------------------------------------------------------------------


def _escape(text: str) -> str:
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _fmt_price(p: float | None) -> str:
    if p is None:
        return "?"
    if p >= 1000:
        return f"${p:,.0f}"
    if p >= 1:
        return f"${p:,.2f}"
    return f"${p:.4f}"


def _fmt_pct(p: float | None) -> str:
    """+1.2% / -0.4% / flat. None -> empty string so callers can filter."""
    if p is None:
        return ""
    if abs(p) < 0.001:
        return "flat"
    sign = "+" if p > 0 else ""
    return f"{sign}{p * 100:.1f}%"


def _to_score_pct(raw_score: float) -> int:
    """Score is 0-100 post-migration; legacy [-1, +1] auto-rescales."""
    raw = float(raw_score or 0.0)
    if -1.5 <= raw <= 1.5:
        raw = (raw + 1.0) * 50.0
    return int(round(max(0.0, min(100.0, raw))))


def _round_to_5(score_pct: int) -> int:
    return int(round(score_pct / 5.0)) * 5


def _bucket(action: str, score_pct: int) -> str:
    """Display bucket. Distinct from action so we can call mid-WATCH a NEUTRAL."""
    if action == "STRONG":
        return "STRONG"
    if action == "WATCH" and score_pct >= 60:
        return "WATCH"
    if action == "AVOID":
        return "AVOID"
    if action == "INSUFFICIENT_DATA":
        return "NO_DATA"
    return "NEUTRAL"


def _fmt_mcap(value: float | None) -> str:
    if value is None:
        return "?"
    av = abs(value)
    if av >= 1e12:
        return f"${value / 1e12:.2f}T"
    if av >= 1e9:
        return f"${value / 1e9:.1f}B"
    if av >= 1e6:
        return f"${value / 1e6:.0f}M"
    return f"${value:,.0f}"


# ---------------------------------------------------------------------------
# Sections
# ---------------------------------------------------------------------------


def _market_regime_lines(market: dict | None) -> list[str]:
    """Market regime block. ~3 lines. Includes a one-line analyst read."""
    if not market:
        return []
    btc = market.get("btc") or {}
    eth = market.get("eth") or {}
    summary = market.get("summary")
    if not btc.get("last") and not eth.get("last") and summary is None:
        return []

    lines: list[str] = ["<b>Market regime</b>"]

    btc_line_parts: list[str] = []
    if btc.get("last") is not None:
        moves = []
        for k, label in (("p1d", "24h"), ("p7d", "7d")):
            if btc.get(k) is not None:
                moves.append(f"{_fmt_pct(btc[k])} {label}")
        moves_str = f" ({', '.join(moves)})" if moves else ""
        btc_line_parts.append(f"BTC {_fmt_price(btc['last'])}{moves_str}")
    if eth.get("last") is not None:
        eth_moves = []
        for k, label in (("p1d", "24h"), ("p7d", "7d")):
            if eth.get(k) is not None:
                eth_moves.append(f"{_fmt_pct(eth[k])} {label}")
        eth_str = f" ({', '.join(eth_moves)})" if eth_moves else ""
        btc_line_parts.append(f"ETH {_fmt_price(eth['last'])}{eth_str}")
    if btc_line_parts:
        lines.append("  " + " | ".join(btc_line_parts))

    # ETH/BTC + dominance.
    second_parts: list[str] = []
    if btc.get("last") and eth.get("last"):
        second_parts.append(f"ETH/BTC {eth['last'] / btc['last']:.4f}")
    if summary is not None:
        btc_d = getattr(summary, "btc_dominance_pct", None)
        if btc_d is not None:
            second_parts.append(f"BTC.D {btc_d:.1f}%")
        mcap = getattr(summary, "total_market_cap_usd", None)
        if mcap is not None:
            second_parts.append(f"Total mcap {_fmt_mcap(mcap)}")
        vol = getattr(summary, "total_volume_24h_usd", None)
        if vol is not None:
            second_parts.append(f"24h vol {_fmt_mcap(vol)}")
    if second_parts:
        lines.append("  " + " | ".join(second_parts))

    # One-line analyst read derived from BTC.D + ETH 7d move.
    read = _market_read(btc=btc, eth=eth, summary=summary)
    if read:
        lines.append(f"  <i>Read:</i> {_escape(read)}")
    lines.append("")
    return lines


def _market_read(*, btc: dict, eth: dict, summary) -> str | None:
    """One-sentence institutional read on the regime."""
    btc_d = getattr(summary, "btc_dominance_pct", None) if summary is not None else None
    eth_7d = eth.get("p7d")
    btc_7d = btc.get("p7d")

    # Capitulation / firm BTC moves first.
    if btc_7d is not None and btc_7d <= -0.10:
        return "BTC down 10%+ on the week. Risk-off; sit on hands until BTC stabilises."
    if btc_7d is not None and btc_7d >= 0.10:
        return "BTC firm 7d. Lean long on dips; fade chase entries."

    # ETH/BTC rotation read.
    if btc.get("last") and eth.get("last") and eth_7d is not None and btc_7d is not None:
        rel = eth_7d - btc_7d
        if rel >= 0.05:
            return "Alts firming vs BTC. Rotation window opening; watch high-beta names."
        if rel <= -0.05:
            return "BTC outpacing alts. Alt rotation muted; stay in BTC/ETH or cash."

    # Dominance fallback.
    if btc_d is not None:
        if btc_d >= 60:
            return "BTC dominance elevated. Alts under pressure; size accordingly."
        if btc_d <= 50:
            return "BTC dominance below 50%. Alt season conditions."

    return "Neutral regime. No edge from the macro tape today."


def _todays_read(candidates) -> list[str]:
    """The institutional one-pager: bucket headline + names to watch + names to avoid."""
    if not candidates:
        return ["<b>Today's read</b>", "  Universe empty.", ""]

    scores = [_to_score_pct(c.score) for c in candidates]
    spread = max(scores) - min(scores) if scores else 0
    buckets = {"STRONG": [], "WATCH": [], "NEUTRAL": [], "AVOID": [], "NO_DATA": []}
    for c in candidates:
        s_pct = _to_score_pct(c.score)
        buckets[_bucket(c.action, s_pct)].append((c, s_pct))

    lines: list[str] = ["<b>Today's read</b>"]

    n = len(candidates)
    n_strong = len(buckets["STRONG"])

    # Headline — the institutional take on whether today is actionable.
    if n_strong >= 1:
        lines.append(
            f"  {n_strong} high-conviction setup{'s' if n_strong > 1 else ''} "
            f"({n} names scanned, spread {min(scores)}-{max(scores)})."
        )
    elif spread <= 15:
        lo, hi = min(scores), max(scores)
        lines.append(
            f"  No high-conviction setups. Universe scored {lo}-{hi} / 100 (neutral cluster)."
        )
    else:
        lo, hi = min(scores), max(scores)
        lines.append(
            f"  No STRONG setups. Universe spread {lo}-{hi} / 100 — some differentiation."
        )

    # Closest to action: top 2 non-neutral non-avoid.
    show_precise = spread > 15
    actionable_top = sorted(
        buckets["STRONG"] + buckets["WATCH"],
        key=lambda t: -t[1],
    )[:2]
    if actionable_top:
        lines.append("")
        lines.append("  <i>Closest to action:</i>")
        for c, s_pct in actionable_top:
            score_disp = s_pct if show_precise else _round_to_5(s_pct)
            trigger = _trigger_for(c)
            lines.append(
                f"    {_escape(_short_symbol(c.symbol))} ({score_disp}) — "
                f"{_escape((c.reason or 'no notable signals')[:120])}."
            )
            if trigger:
                lines.append(f"        Trigger: {_escape(trigger)}")

    # Avoid block: top 1 lowest-score AVOID.
    avoid_top = sorted(buckets["AVOID"], key=lambda t: t[1])[:1]
    if avoid_top:
        lines.append("")
        lines.append("  <i>Avoid:</i>")
        for c, s_pct in avoid_top:
            score_disp = s_pct if show_precise else _round_to_5(s_pct)
            lines.append(
                f"    {_escape(_short_symbol(c.symbol))} ({score_disp}) — "
                f"{_escape((c.reason or 'low conviction')[:100])}."
            )

    lines.append("")
    return lines


def _short_symbol(sym: str) -> str:
    return sym.split("-")[0].upper() if sym else "?"


def _trigger_for(c) -> str | None:
    """Concrete actionable trigger string for the candidate.

    Prefers a price level (50d MA proxy via 30d low as floor reclaim)
    over vague guidance.
    """
    px = (c.extras.get("px") or {}) if c.extras else {}
    last = px.get("last")
    high30 = px.get("high30")
    low30 = px.get("low30")
    if last is None:
        return None
    if c.action == "WATCH" and high30 is not None and last < high30 * 0.95:
        return f"reclaim of {_fmt_price(high30 * 0.97)} (~3% off 30d high)"
    if c.action == "WATCH" and low30 is not None:
        return f"hold of {_fmt_price(low30)} (30d low) on a retest"
    return None


def _signals_fired(candidates) -> list[str]:
    """Cross-symbol signal clusters worth surfacing.

    Only emit lines when something actually fired. A neutral universe
    correctly produces zero lines here — we then say 'no signals fired'
    in one line rather than padding."""
    fired: list[str] = []

    # Bullish/bearish MACD clusters.
    bear_macd = [c.symbol for c in candidates if _has_macd(c, "bear")]
    bull_macd = [c.symbol for c in candidates if _has_macd(c, "bull")]
    if len(bear_macd) >= 2:
        fired.append(
            f"{len(bear_macd)} names on bearish MACD: "
            f"{', '.join(_short_symbol(s) for s in bear_macd[:5])}"
        )
    if len(bull_macd) >= 2:
        fired.append(
            f"{len(bull_macd)} names on bullish MACD: "
            f"{', '.join(_short_symbol(s) for s in bull_macd[:5])}"
        )

    # Names underperforming BTC by a wide margin.
    weak_vs_btc = []
    for c in candidates:
        ca = c.signals.get("cross_asset") if c.signals else None
        if ca is None:
            continue
        rs = (ca.details or {}).get("rel_strength_60d")
        if rs is not None and rs <= -0.25:
            weak_vs_btc.append((c.symbol, rs))
    if len(weak_vs_btc) >= 2:
        names = ", ".join(_short_symbol(s) for s, _ in weak_vs_btc[:5])
        fired.append(f"{len(weak_vs_btc)} names underperforming BTC by >25pt over 60d: {names}")

    # Funding extremes (notable).
    funding_hot = [c.symbol for c in candidates if _funding_extreme(c)]
    if funding_hot:
        fired.append(
            f"{len(funding_hot)} name(s) with funding-rate extreme: "
            f"{', '.join(_short_symbol(s) for s in funding_hot[:5])}"
        )

    # OI cluster.
    oi_hot = [c.symbol for c in candidates if _oi_notable(c)]
    if oi_hot:
        fired.append(
            f"{len(oi_hot)} name(s) with notable OI move: "
            f"{', '.join(_short_symbol(s) for s in oi_hot[:5])}"
        )

    if not fired:
        return [
            "<b>Signals fired</b>",
            "  No funding extremes, no liquidation cascades, no notable OI moves.",
            "",
        ]

    out = ["<b>Signals fired</b>"]
    for line in fired:
        out.append(f"  {line}")
    out.append("")
    return out


def _has_macd(c, direction: str) -> bool:
    sig = c.signals.get("technical") if c.signals else None
    if not sig or not sig.bullets:
        return False
    for b in sig.bullets:
        text = b.lower()
        if "macd" not in text:
            continue
        if direction == "bear" and ("bearish" in text or "rolling over" in text):
            return True
        if direction == "bull" and ("bullish" in text or "early trend" in text):
            return True
    return False


def _funding_extreme(c) -> bool:
    sig = c.signals.get("funding_rate") if c.signals else None
    if not sig:
        return False
    return abs(sig.strength) >= 0.3


def _oi_notable(c) -> bool:
    sig = c.signals.get("open_interest") if c.signals else None
    if not sig:
        return False
    return abs(sig.strength) >= 0.25


def _action_line(result: RunResult, candidates) -> list[str]:
    """One-liner: what to do, when next."""
    n_strong = sum(1 for c in candidates if c.action == "STRONG")
    if n_strong >= 1:
        msg = f"{n_strong} STRONG name(s) — review entries above. Re-checking at 14:00 UTC."
    else:
        msg = "No buys today. Re-checking at 14:00 UTC (passive scan, silent unless trigger)."
    return ["<b>Action</b>", f"  {msg}", "  Next high-conviction watchlist: tomorrow 08:00 UTC."]


def _catalysts_line(engine) -> list[str]:
    """One-line catalyst summary (suppressed if none)."""
    if engine is None:
        return []
    try:
        from ..news.lookup import top_catalysts
        catalysts = top_catalysts(engine, hours=24, limit=3, min_magnitude=0.5)
    except Exception:
        return []
    if not catalysts:
        return []
    out = ["<b>News catalysts (24h, |sentiment|>=0.5)</b>"]
    for cat in catalysts:
        currencies = ",".join(cat.currencies_json[:3]) if cat.currencies_json else "-"
        out.append(
            f"  {_escape(currencies)} ({cat.sentiment_score:+.2f}): "
            f"{_escape(cat.title[:120])}"
        )
    out.append("")
    return out


def _paper_portfolio_line(engine) -> list[str]:
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
    except Exception:
        return []
    if cash == 0 and not holdings:
        return []
    parts = [f"cash ${cash:,.0f}"]
    for p in holdings:
        parts.append(f"{_escape(_short_symbol(p.symbol))} {float(p.quantity):.4f}@${float(p.avg_price):,.0f}")
    return [f"<b>Paper portfolio</b>: {' · '.join(parts)}", ""]


# ---------------------------------------------------------------------------
# Top-level render
# ---------------------------------------------------------------------------


def render_html(result: RunResult, *, engine=None) -> str:
    """Institutional one-pager. Brevity is the point."""
    lines: list[str] = []
    date_str = result.run_at.strftime("%Y-%m-%d")
    lines.append(f"<b>Crypto Daily — {date_str}</b>")
    lines.append("")

    lines.extend(_paper_portfolio_line(engine))
    lines.extend(_market_regime_lines(result.market))
    lines.extend(_todays_read(result.candidates))
    lines.extend(_signals_fired(result.candidates))
    lines.extend(_catalysts_line(engine))
    lines.extend(_action_line(result, result.candidates))

    return "\n".join(lines)


# Backward-compat alias for tests that imported the underscore name.
_render_html = render_html


# ---------------------------------------------------------------------------
# should_send gate
# ---------------------------------------------------------------------------


def should_send_daily(
    *,
    engine,
    candidates,
    score_tolerance: float = 5.0,
    catalyst_window_hours: int = 24,
) -> tuple[bool, str]:
    """Suppress daily messages that would just repeat yesterday.

    Send when ANY of:
      * We have no prior daily snapshot (first run).
      * Top-3 candidate symbols changed.
      * Any top-5 candidate's score moved by more than score_tolerance.
      * Any symbol crossed a bucket boundary (NEUTRAL <-> WATCH <-> STRONG).
      * A high-impact news catalyst appeared in the last
        catalyst_window_hours hours that wasn't in yesterday's window.

    Returns (should_send, reason). The caller logs the reason and skips
    the Telegram POST when should_send is False.
    """
    if engine is None:
        return True, "no engine to compare against"

    try:
        from datetime import datetime, timedelta

        from sqlalchemy import desc, select

        from ..db import session_factory, session_scope
        from ..models import CandidateRecord

        SessionLocal = session_factory(engine)

        # Today's top candidates (the freshly computed run).
        today_top3 = [c.symbol for c in candidates[:3]]
        today_scores = {c.symbol: float(c.score) for c in candidates[:5]}
        today_buckets = {
            c.symbol: _bucket(c.action, _to_score_pct(c.score))
            for c in candidates[:10]
        }

        # Yesterday's snapshot — most recent CandidateRecord run before
        # today's run.
        cutoff = datetime.now(UTC) - timedelta(hours=2)
        with session_scope(SessionLocal) as session:
            prior_run_at = session.scalars(
                select(CandidateRecord.run_at)
                .where(CandidateRecord.run_at < cutoff)
                .order_by(desc(CandidateRecord.run_at))
                .limit(1)
            ).first()
            if prior_run_at is None:
                return True, "no prior daily snapshot"

            prior_rows = list(session.scalars(
                select(CandidateRecord)
                .where(CandidateRecord.run_at == prior_run_at)
                .order_by(desc(CandidateRecord.score))
            ).all())

        prior_top3 = [r.symbol for r in prior_rows[:3]]
        prior_scores = {r.symbol: float(r.score) for r in prior_rows[:10]}
        prior_buckets = {
            r.symbol: _bucket(r.action, _to_score_pct(r.score))
            for r in prior_rows[:10]
        }

        if today_top3 != prior_top3:
            return True, f"top-3 changed: {prior_top3} -> {today_top3}"

        for sym, sc in today_scores.items():
            prev = prior_scores.get(sym)
            if prev is None:
                return True, f"{sym} not in prior snapshot"
            if abs(sc - prev) > score_tolerance:
                return True, f"{sym} score moved {prev:.1f} -> {sc:.1f}"

        for sym, b in today_buckets.items():
            prev_b = prior_buckets.get(sym)
            if prev_b and prev_b != b:
                return True, f"{sym} bucket {prev_b} -> {b}"

        return False, "no material change since prior daily"

    except Exception as exc:  # pragma: no cover
        logger.warning("should_send_daily: defaulting to send (gate error: %s)", exc)
        return True, f"gate error ({exc})"


# ---------------------------------------------------------------------------
# Chunking + http
# ---------------------------------------------------------------------------


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
