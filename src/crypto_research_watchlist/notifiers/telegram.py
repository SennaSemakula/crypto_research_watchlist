"""Telegram bot notifier - daily crypto rotation render.

Mirrors the stock side's "Daily Capital Rotation" template:

  * Header with date.
  * Paper portfolio block (cash + positions + PnL + benchmark deltas).
  * Top story banner (single highest |sentiment| 24h headline).
  * Since-your-last-check (24h news bullets, one per coin).
  * Ranked candidates - every candidate gets a panel matching its
    decision (BUY_NOW / STARTER / WAIT / AVOID).
  * Best use of next $X - capital allocation suggestion.
  * Footer.

The CandidateDecision attached to each Candidate.extras carries the
heavy lifting; this module is presentation. Multi-part chunking on
section boundaries keeps the message under Telegram's 4096-char limit
with ``(part X/Y)`` headers.
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
        chunks = _chunk_sections(body_html, limit=_MAX_PER_MESSAGE_CHARS)

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
# Formatting helpers
# ---------------------------------------------------------------------------


def _escape(text: str) -> str:
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _short_symbol(sym: str) -> str:
    return sym.split("-")[0].upper() if sym else "?"


def _fmt_price(p: float | None) -> str:
    if p is None:
        return "?"
    if p >= 1000:
        return f"${p:,.0f}"
    if p >= 1:
        return f"${p:,.2f}"
    return f"${p:.4f}"


def _fmt_pct(p: float | None) -> str:
    if p is None:
        return ""
    if abs(p) < 0.001:
        return "flat"
    sign = "+" if p > 0 else ""
    return f"{sign}{p * 100:.1f}%"


def _to_score_pct(raw_score: float) -> int:
    raw = float(raw_score or 0.0)
    if -1.5 <= raw <= 1.5:
        raw = (raw + 1.0) * 50.0
    return int(round(max(0.0, min(100.0, raw))))


def _bucket(action: str, score_pct: int) -> str:
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


_DECISION_PRIMARY_EMOJI = {
    "BUY_NOW": "\U0001F7E2",
    "STARTER": "\U0001F7E1",
    "WAIT": "\U0001F7E0",
    "AVOID": "\U0001F6AB",
}

_DECISION_LABEL_TOKEN = {
    "BUY_NOW": "\U0001F7E2 BUY NOW",
    "STARTER": "\U0001F7E1 STARTER",
    "WAIT": "\U0001F7E0 WAIT",
    "AVOID": "\U0001F6AB AVOID",
}

_TAG_EMOJI = {
    "material event": "⚡",
    "breaking positive": "\U0001F7E2",
    "breaking negative": "\U0001F534",
    "chase trap": "\U0001F6AB",
    "at 60d peak": "⚠️",
    "DIP -10% 5d": "✅",
    "OI surge": "\U0001F525",
}


_SYMBOL_TO_NAME = {
    "BTC": "Bitcoin",
    "ETH": "Ethereum",
    "SOL": "Solana",
    "BNB": "BNB",
    "XRP": "XRP",
    "ADA": "Cardano",
    "AVAX": "Avalanche",
    "DOT": "Polkadot",
    "LINK": "Chainlink",
    "MATIC": "Polygon",
    "POL": "Polygon",
}


def _coin_full_name(symbol: str) -> str:
    sym = _short_symbol(symbol)
    return _SYMBOL_TO_NAME.get(sym, sym)


# ---------------------------------------------------------------------------
# Sections
# ---------------------------------------------------------------------------


def _header_section(result: RunResult) -> list[str]:
    date_str = result.run_at.strftime("%Y-%m-%d")
    return [
        f"\U0001F4CA <b>Daily Crypto Rotation - {_escape(date_str)}</b>",
    ]


def _paper_portfolio_section(result: RunResult, engine) -> list[str]:
    """My paper portfolio block. Always shown (even with no positions).

    Pulls cash + positions from the paper-trading tables when ``engine``
    is supplied; otherwise renders a default $5000 cash empty book."""
    cash = 5000.0
    holdings: list = []
    positions_value = 0.0
    pnl_total = cash - 5000.0

    if engine is not None:
        try:
            from sqlalchemy import select

            from ..db import session_factory, session_scope
            from ..models import PaperCash, PaperPosition
            SessionLocal = session_factory(engine)
            with session_scope(SessionLocal) as session:
                cash_row = session.get(PaperCash, 1)
                if cash_row is not None:
                    cash = float(cash_row.cash_usd)
                positions = list(session.scalars(select(PaperPosition)).all())
                for p in positions:
                    qty = float(p.quantity or 0.0)
                    if qty <= 0:
                        continue
                    avg = float(p.avg_price or 0.0)
                    holdings.append((p.symbol, qty, avg))
                    positions_value += qty * avg
        except Exception:
            pass

    total = cash + positions_value
    deployed = positions_value
    pnl_total = total - 5000.0
    pnl_pct = pnl_total / 5000.0 if 5000.0 else 0.0
    pnl_emoji = "\U0001F7E2" if pnl_total >= 0 else "\U0001F534"
    sign = "+" if pnl_total >= 0 else ""
    pnl_pct_sign = "+" if pnl_pct >= 0 else ""
    deployed_repr = f"${deployed:,.0f}" if deployed else "$0"

    lines: list[str] = []
    lines.append("\U0001F4BC <b>MY PAPER PORTFOLIO</b>")
    lines.append(
        f"   Total: ${total:,.2f}  (cash ${cash:,.2f} + positions ${positions_value:,.2f})"
    )
    lines.append(
        f"   PnL: {pnl_emoji} ${sign}{pnl_total:,.2f} ({pnl_pct_sign}{pnl_pct * 100:.2f}%)"
        f" on {deployed_repr} deployed"
    )
    if holdings:
        bits = ", ".join(
            f"{_short_symbol(s)} {qty:.4f}@${avg:,.0f}" for s, qty, avg in holdings
        )
        lines.append(f"   Holdings: {bits}")
    else:
        lines.append("   Holdings: (none)")

    bench_parts = _benchmark_parts(result)
    if bench_parts:
        lines.append("   vs benchmarks: You " + _fmt_pct(pnl_pct) + bench_parts)
    return lines


def _benchmark_parts(result: RunResult) -> str:
    """ ' · BTC +2.4%  · ETH +0.8%  · Total mcap +1.5%' """
    market = result.market or {}
    btc = market.get("btc") or {}
    eth = market.get("eth") or {}
    summary = market.get("summary")
    parts: list[str] = []
    if btc.get("p1d") is not None:
        parts.append(f"BTC {_fmt_pct(btc['p1d'])}")
    if eth.get("p1d") is not None:
        parts.append(f"ETH {_fmt_pct(eth['p1d'])}")
    # Total mcap: we don't have a 24h % field; use a flat '(?)' if absent.
    if summary is not None:
        mcap_chg = getattr(summary, "total_market_cap_change_24h", None)
        if mcap_chg is not None:
            parts.append(f"Total mcap {_fmt_pct(mcap_chg / 100.0 if abs(mcap_chg) > 1 else mcap_chg)}")
    if not parts:
        return ""
    return "  ·  " + "  ·  ".join(parts)


def _top_story_section(engine) -> list[str]:
    """\U0001F6A8\U0001F6A8 TOP STORY - single highest |sentiment| 24h article that
    mentions a universe coin. Skipped if no qualifying article."""
    if engine is None:
        return []
    try:
        from ..news.lookup import top_catalysts
        catalysts = top_catalysts(engine, hours=24, limit=1, min_magnitude=0.5)
    except Exception:
        return []
    if not catalysts:
        return []
    article = catalysts[0]
    currencies = list(getattr(article, "currencies_json", None) or [])
    sym = currencies[0] if currencies else ""
    if not sym:
        return []
    out: list[str] = []
    out.append("\U0001F6A8\U0001F6A8 <b>TOP STORY</b>")
    name = _coin_full_name(sym)
    out.append(f"   {_escape(sym)} ({_escape(name)})")
    out.append(f"   {_escape(article.title)}")
    sent = float(getattr(article, "sentiment_score", 0.0) or 0.0)
    why = _why_it_matters(article, sent)
    if why:
        out.append(f"   → Why it matters: {_escape(why)}")
    return out


def _why_it_matters(article, sentiment: float) -> str:
    title = getattr(article, "title", "") or ""
    if sentiment >= 0.5:
        return "Sentiment skews positive; could re-rate the affected name in the next 1-3 sessions."
    if sentiment <= -0.5:
        return "Sentiment skews negative; expect a 1-3 session drag until clarity returns."
    if "etf" in title.lower():
        return "ETF flow signals retail bid; watch for follow-through."
    return "Watch for follow-through in the next 24-48h."


def _since_last_check_section(engine) -> list[str]:
    """\U0001F4F0 SINCE YOUR LAST CHECK - last 24h news bullets, deduped per
    coin, sentiment-coloured. Up to 8."""
    if engine is None:
        return []
    try:
        from datetime import datetime, timedelta

        from sqlalchemy import desc
        from sqlalchemy.orm import Session

        from ..models import NewsArticle
        cutoff = datetime.now(UTC) - timedelta(hours=24)
        with Session(engine) as session:
            rows = list(session.query(NewsArticle)
                        .filter(NewsArticle.published_at >= cutoff)
                        .order_by(desc(NewsArticle.published_at))
                        .limit(50)
                        .all())
            for r in rows:
                session.expunge(r)
    except Exception:
        return []
    if not rows:
        return []

    seen_syms: set[str] = set()
    bullets: list[str] = []
    for art in rows:
        currencies = list(getattr(art, "currencies_json", None) or [])
        if not currencies:
            continue
        sym = currencies[0]
        if sym in seen_syms:
            continue
        seen_syms.add(sym)
        sent = float(getattr(art, "sentiment_score", 0.0) or 0.0)
        if sent >= 0.3:
            dot = "\U0001F7E2"
        elif sent <= -0.3:
            dot = "\U0001F534"
        else:
            dot = "⚡"
        title = getattr(art, "title", "")
        source = getattr(art, "source", "")
        suffix = f" - {source}" if source else ""
        bullets.append(f"   {dot} {_escape(sym)}: {_escape(title[:100])}{_escape(suffix)}")
        if len(bullets) >= 8:
            break
    if not bullets:
        return []
    out = ["\U0001F4F0 <b>SINCE YOUR LAST CHECK - last 24h</b>"]
    out.extend(bullets)
    return out


def _ranked_candidates_section(result: RunResult) -> list[str]:
    """\U0001F4CA RANKED CANDIDATES - every candidate gets a panel."""
    if not result.candidates:
        return [
            "\U0001F4CA <b>RANKED CANDIDATES</b>",
            "   <i>No candidates today.</i>",
        ]
    out: list[str] = ["\U0001F4CA <b>RANKED CANDIDATES</b> (sorted by score)"]
    for idx, c in enumerate(result.candidates, 1):
        out.extend(_candidate_panel(idx, c))
        out.append("")
    if out and out[-1] == "":
        out.pop()
    return out


def _candidate_panel(rank: int, c) -> list[str]:
    """Emit the per-candidate panel."""
    extras = c.extras or {}
    decision_dict = extras.get("decision") or {}
    classification = decision_dict.get("classification", "HIGHER-RISK")
    decision = decision_dict.get("decision", "WAIT")
    tag = decision_dict.get("tag", "")
    why = decision_dict.get("why_text", "")
    bullets = decision_dict.get("value_bullets", []) or []
    main_risk = decision_dict.get("main_risk", "")
    technical_summary = decision_dict.get("technical_summary", "")
    buy_zone = decision_dict.get("buy_zone")
    buy_if = decision_dict.get("buy_if_price")
    max_chase = decision_dict.get("max_chase")
    sell_half = decision_dict.get("sell_half_price")
    sell_quarter = decision_dict.get("sell_quarter_price")
    stop = decision_dict.get("stop_price")
    target_base = decision_dict.get("target_base")
    target_bull = decision_dict.get("target_bull")
    review_days = decision_dict.get("review_in_days", 7)
    break_thesis = decision_dict.get("break_thesis_if", "")
    suggested_size = decision_dict.get("suggested_size_usd")

    primary_emoji = _DECISION_PRIMARY_EMOJI.get(decision, "•")
    label_token = _DECISION_LABEL_TOKEN.get(decision, decision)
    sym = _short_symbol(c.symbol)
    score_pct = _to_score_pct(c.score)

    head = (
        f"{primary_emoji} {rank}. <b>{_escape(sym)}</b> "
        f"- {_escape(classification)} - {score_pct}/100"
    )
    suffix_parts: list[str] = []
    if tag:
        tag_emoji = _TAG_EMOJI.get(tag, "")
        if tag_emoji:
            suffix_parts.append(f"{tag_emoji} {_escape(tag)}")
        else:
            suffix_parts.append(_escape(tag))
    suffix_parts.append(f"[{label_token}]")
    header = head + "  · " + "  · ".join(suffix_parts)

    block: list[str] = [header]

    px = extras.get("px") or {}
    last = px.get("last")

    # Inline price warning (chase / dip / peak).
    inline_warn = _inline_price_warning(tag, px)
    if inline_warn:
        block.append(f"   {inline_warn}")

    # Buy line for BUY_NOW / STARTER.
    if decision in ("BUY_NOW", "STARTER") and suggested_size:
        block.append(f"   Buy: <b>${suggested_size:,.0f}</b> now")

    why_label = {
        "BUY_NOW": "Why buy",
        "STARTER": "Why starter",
        "WAIT": "Why wait",
        "AVOID": "Why avoid",
    }.get(decision, "Why")
    if why:
        block.append(f"   <b>{why_label}:</b> {_escape(why)}")

    # Value bullets (indented, with check-marks).
    if bullets and decision != "WAIT":
        for b in bullets[:3]:
            block.append(f"     ✅ {_escape(b)}")
    elif bullets:
        # WAIT keeps a single supporting bullet.
        block.append(f"     ✅ {_escape(bullets[0])}")

    # Main risk (BUY_NOW only).
    if decision == "BUY_NOW" and main_risk:
        block.append(f"   <b>Main risk:</b> {_escape(main_risk)}")

    # Technical summary (always one line if available).
    if technical_summary:
        block.append(f"   \U0001F3E6 {_escape(technical_summary)}")

    # Buy zone instruction.
    if decision in ("BUY_NOW", "STARTER") and buy_zone:
        lo, hi = buy_zone
        block.append(
            f"   \U0001F3AF Buy on strength around {_fmt_price(lo)}-{_fmt_price(hi)} "
            f"(don't chase above {_fmt_price(max_chase)})"
        )
    elif decision == "WAIT" and buy_if is not None:
        ma_label = ""
        block.append(
            f"   <b>Buy if:</b> drops to {_fmt_price(buy_if)}{ma_label}"
        )
        if buy_zone:
            lo, hi = buy_zone
            block.append(
                f"   \U0001F3AF Wait for a dip then buy between {_fmt_price(lo)}-{_fmt_price(hi)}"
            )

    # Targets / stop visible for everyone with price data.
    if sell_half is not None and last:
        pct = (sell_half / last - 1.0) * 100
        block.append(
            f"   ✅ Sell half at {_fmt_price(sell_half)} ({pct:+.0f}%)"
        )
    if sell_quarter is not None and last:
        pct = (sell_quarter / last - 1.0) * 100
        block.append(
            f"   ✅ Sell another quarter at {_fmt_price(sell_quarter)} ({pct:+.0f}%)"
        )
    if stop is not None and last:
        pct = (stop / last - 1.0) * 100
        block.append(
            f"   \U0001F6D1 Sell everything if it drops to {_fmt_price(stop)} ({pct:+.0f}%)"
        )

    # Entry / Max chase (CORE/MAJOR + BUY/STARTER only).
    if decision in ("BUY_NOW", "STARTER") and classification in ("CORE", "MAJOR"):
        if buy_zone:
            block.append(f"   Entry: ≤ {_fmt_price(buy_zone[1])}")
        if max_chase is not None:
            block.append(f"   Max chase: {_fmt_price(max_chase)}")
    if target_base is not None:
        target_line = f"   Target: {_fmt_price(target_base)} base"
        if target_bull is not None:
            target_line += f" / {_fmt_price(target_bull)} bull"
        block.append(target_line)

    block.append(f"   Review: {review_days} days")
    if break_thesis:
        block.append(f"   Break thesis if: {_escape(break_thesis)}")
    return block


def _inline_price_warning(tag: str, px: dict) -> str:
    """One-line warning embedded under the header for chase/dip/peak."""
    if tag == "DIP -10% 5d":
        p5d = px.get("p5d") or px.get("p7d")
        if p5d is not None:
            return f"⚠️ DIP ({p5d * 100:+.0f}% 5d)"
        return "⚠️ DIP"
    if tag == "chase trap":
        p5d = px.get("p5d") or px.get("p7d")
        if p5d is not None:
            return f"\U0001F6AB CHASE (+{p5d * 100:.0f}% 5d, at peak)"
        return "\U0001F6AB CHASE"
    if tag == "at 60d peak":
        return "⚠️ at 60d peak"
    return ""


def _best_use_section(result: RunResult) -> list[str]:
    """\U0001F4B0 BEST USE OF NEXT $X - deploy plan summary."""
    out: list[str] = ["\U0001F4B0 <b>BEST USE OF NEXT $5,000</b>"]
    buy_now = []
    starters = []
    for c in result.candidates:
        d = (c.extras or {}).get("decision") or {}
        if d.get("decision") == "BUY_NOW":
            buy_now.append((c, d))
        elif d.get("decision") == "STARTER":
            starters.append((c, d))

    deploy_lines: list[str] = []
    deploy_total = 0.0
    for c, d in buy_now:
        size = d.get("suggested_size_usd") or 0
        if not size:
            continue
        zone = d.get("buy_zone")
        cap = ""
        if zone:
            cap = f" at ≤ {_fmt_price(zone[1])}"
        deploy_lines.append(
            f"   Deploy ${size:,.0f} into {_short_symbol(c.symbol)}{cap}"
            f" (BUY NOW conviction)"
        )
        deploy_total += size
    for c, d in starters:
        size = d.get("suggested_size_usd") or 0
        if not size:
            continue
        deploy_lines.append(
            f"   Deploy ${size:,.0f} into {_short_symbol(c.symbol)} (STARTER)"
        )
        deploy_total += size

    if deploy_lines:
        out.extend(deploy_lines)
        remaining = max(0.0, 5000.0 - deploy_total)
        if remaining:
            out.append(
                f"   Hold ${remaining:,.0f} in cash (regime not supportive of full deployment)"
            )
    else:
        out.append("   Hold $5,000 in cash (no high-conviction setups today)")

    hidden = max(0, len(result.candidates) - 10)
    if hidden:
        out.append("")
        out.append(
            f"   Hidden from phone: {hidden} more candidates - "
            "see attached briefing for detail"
        )
    return out


def _footer_section() -> list[str]:
    return ["<i>Automated research - not advice. No trades placed.</i>"]


# ---------------------------------------------------------------------------
# Top-level render
# ---------------------------------------------------------------------------


def render_html(result: RunResult, *, engine=None) -> str:
    """Multi-section daily render. Sections separated by ``\\n\\n``."""
    sections: list[list[str]] = []
    sections.append(_header_section(result))
    sections.append(_paper_portfolio_section(result, engine))
    top_story = _top_story_section(engine)
    if top_story:
        sections.append(top_story)
    since_last = _since_last_check_section(engine)
    if since_last:
        sections.append(since_last)
    sections.append(_ranked_candidates_section(result))
    sections.append(_best_use_section(result))
    sections.append(_footer_section())

    blocks = ["\n".join(s) for s in sections if s]
    return "\n\n".join(blocks)


# Backward-compat alias for tests that imported the underscore name.
_render_html = render_html


# ---------------------------------------------------------------------------
# should_send gate (legacy)
# ---------------------------------------------------------------------------


def should_send_daily(
    *,
    engine,
    candidates,
    score_tolerance: float = 5.0,
    catalyst_window_hours: int = 24,
) -> tuple[bool, str]:
    """Suppress daily messages that would just repeat yesterday.

    DEPRECATED: the daily watchlist is the digest now and always sends.
    Retained so legacy tests + any external callers keep working.

    Send when ANY of:
      * We have no prior daily snapshot (first run).
      * Top-3 candidate symbols changed.
      * Any top-5 candidate's score moved by more than score_tolerance.
      * Any symbol crossed a bucket boundary (NEUTRAL <-> WATCH <-> STRONG).
    """
    if engine is None:
        return True, "no engine to compare against"

    try:
        from datetime import datetime, timedelta

        from sqlalchemy import desc, select

        from ..db import session_factory, session_scope
        from ..models import CandidateRecord

        SessionLocal = session_factory(engine)

        today_top3 = [c.symbol for c in candidates[:3]]
        today_scores = {c.symbol: float(c.score) for c in candidates[:5]}
        today_buckets = {
            c.symbol: _bucket(c.action, _to_score_pct(c.score))
            for c in candidates[:10]
        }

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
# Multi-part chunking
# ---------------------------------------------------------------------------


def _chunk_sections(text: str, *, limit: int) -> list[str]:
    """Chunk on section boundaries (blank lines) when total > limit."""
    if len(text) <= limit:
        return [text]
    sections = text.split("\n\n")
    out: list[str] = []
    cur: list[str] = []
    cur_len = 0
    for sec in sections:
        sec_len = len(sec) + (2 if cur else 0)
        if cur_len + sec_len > limit and cur:
            out.append("\n\n".join(cur))
            cur = [sec]
            cur_len = len(sec)
            continue
        if len(sec) > limit:
            # Single section too big; fall back to line-chunking it.
            if cur:
                out.append("\n\n".join(cur))
                cur = []
                cur_len = 0
            out.extend(_chunk_lines(sec, limit=limit))
            continue
        cur.append(sec)
        cur_len += sec_len
    if cur:
        out.append("\n\n".join(cur))
    return out


def _chunk_lines(text: str, *, limit: int) -> list[str]:
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


# Legacy alias kept for any external imports.
_chunk = _chunk_sections


def _make_httpx():
    import httpx
    return httpx.Client()
