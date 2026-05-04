"""Per-candidate decision enrichment.

Mirrors the stock side's decision shape but for crypto. For each scored
Candidate this module produces a ``CandidateDecision`` capturing:

  * classification (CORE / MAJOR / MID-CAP / HIGHER-RISK)
  * decision (BUY_NOW / STARTER / WAIT / AVOID)
  * tag (material event / breaking positive / breaking negative /
    chase trap / at 60d peak / DIP / OI surge / ...)
  * a one-line ``why_text`` and 2-4 supporting ``value_bullets``
  * ``main_risk`` and a compact ``technical_summary``
  * ATR-derived price targets (buy zone, max chase, sell-half, sell-quarter,
    stop, base / bull targets)
  * ``review_in_days`` and ``break_thesis_if`` invalidation
  * ``suggested_size_usd`` for BUY_NOW / STARTER ($5,000 paper book)

Decisions are computed from existing signals + price extras + news. All
of this is rendered by ``notifiers/telegram.py`` into the per-candidate
panel that mirrors the stock template.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

CORE_SYMBOLS = {"BTC", "ETH"}
MAJOR_SYMBOLS = {"SOL", "BNB", "XRP", "ADA"}
MID_CAP_SYMBOLS = {"AVAX", "DOT", "LINK", "MATIC", "POL"}

# Action thresholds; mirror config.yml defaults so tests can run without
# loading config.
STRONG_THRESHOLD = 64.5
STARTER_THRESHOLD = 55.0
AVOID_THRESHOLD = 40.5

CHASE_5D = 0.25
PEAK_FRACTION = 0.97
DIP_5D = -0.10
OI_SURGE_RATIO = 1.20
OI_SURGE_FLAT_BAND = 0.03

POSITIVE_NEWS_SENT = 0.5
NEGATIVE_NEWS_SENT = -0.5
STARTER_NEWS_SENT = 0.4
AVOID_NEWS_SENT = -0.5


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


@dataclass(slots=True)
class CandidateDecision:
    classification: str
    decision: str
    tag: str
    why_text: str
    value_bullets: list[str] = field(default_factory=list)
    main_risk: str = ""
    technical_summary: str = ""
    buy_if_price: float | None = None
    buy_zone: tuple[float, float] | None = None
    max_chase: float | None = None
    sell_half_price: float | None = None
    sell_quarter_price: float | None = None
    stop_price: float | None = None
    target_base: float | None = None
    target_bull: float | None = None
    review_in_days: int = 7
    break_thesis_if: str = ""
    suggested_size_usd: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "classification": self.classification,
            "decision": self.decision,
            "tag": self.tag,
            "why_text": self.why_text,
            "value_bullets": list(self.value_bullets),
            "main_risk": self.main_risk,
            "technical_summary": self.technical_summary,
            "buy_if_price": self.buy_if_price,
            "buy_zone": list(self.buy_zone) if self.buy_zone else None,
            "max_chase": self.max_chase,
            "sell_half_price": self.sell_half_price,
            "sell_quarter_price": self.sell_quarter_price,
            "stop_price": self.stop_price,
            "target_base": self.target_base,
            "target_bull": self.target_bull,
            "review_in_days": self.review_in_days,
            "break_thesis_if": self.break_thesis_if,
            "suggested_size_usd": self.suggested_size_usd,
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _short_symbol(symbol: str) -> str:
    return symbol.split("-")[0].upper() if symbol else ""


def coin_name(symbol: str) -> str:
    sym = _short_symbol(symbol)
    return _SYMBOL_TO_NAME.get(sym, sym)


def classify(symbol: str) -> str:
    sym = _short_symbol(symbol)
    if sym in CORE_SYMBOLS:
        return "CORE"
    if sym in MAJOR_SYMBOLS:
        return "MAJOR"
    if sym in MID_CAP_SYMBOLS:
        return "MID-CAP"
    return "HIGHER-RISK"


def _px(candidate) -> dict:
    extras = getattr(candidate, "extras", None) or {}
    return extras.get("px") or {}


def _news_for_symbol(symbol: str, news_by_symbol: dict[str, list]) -> list:
    return news_by_symbol.get(_short_symbol(symbol), []) or []


def _strongest_news(articles) -> Any | None:
    if not articles:
        return None
    return max(articles, key=lambda a: abs(getattr(a, "sentiment_score", 0.0) or 0.0))


def pick_tag(candidate, articles) -> str:
    """Pick the highest-priority inline tag for a candidate."""
    px = _px(candidate)
    p5d = _five_day_return(px)
    last = px.get("last")
    high60 = px.get("high60") or px.get("high30")

    if p5d is not None and p5d > CHASE_5D:
        return "chase trap"

    strongest = _strongest_news(articles)
    if strongest is not None:
        sent = float(getattr(strongest, "sentiment_score", 0.0) or 0.0)
        if sent >= POSITIVE_NEWS_SENT:
            return "breaking positive"
        if sent <= NEGATIVE_NEWS_SENT:
            return "breaking negative"
        # Any news at all in the 24h window is a material-event tag.
        return "material event"

    if last is not None and high60 is not None and last >= PEAK_FRACTION * high60:
        return "at 60d peak"

    if p5d is not None and p5d <= DIP_5D:
        return "DIP -10% 5d"

    extras = getattr(candidate, "extras", None) or {}
    oi_today = extras.get("oi_today")
    oi_7d = extras.get("oi_7d_ago")
    p7d = px.get("p7d")
    if oi_today and oi_7d and oi_7d > 0:
        ratio = oi_today / oi_7d
        if ratio >= OI_SURGE_RATIO and p7d is not None and abs(p7d) < OI_SURGE_FLAT_BAND:
            return "OI surge"

    return ""


def _five_day_return(px: dict) -> float | None:
    """Approximate 5d return from extras. Falls back to p7d if absent."""
    if not px:
        return None
    if px.get("p5d") is not None:
        return float(px["p5d"])
    return px.get("p7d")


def pick_decision(candidate, articles, *, tag: str = "") -> str:
    """Decision rules per spec.

    BUY_NOW   if score >= STRONG_THRESHOLD AND no chase-trap.
    STARTER   if score >= STARTER_THRESHOLD AND positive 24h news AND no chase-trap.
    AVOID     if score < AVOID_THRESHOLD OR fresh major negative news.
    WAIT      otherwise.
    """
    score = float(getattr(candidate, "score", 0.0) or 0.0)
    px = _px(candidate)
    p5d = _five_day_return(px)
    chase = (p5d is not None and p5d > CHASE_5D) or tag == "chase trap"

    strongest = _strongest_news(articles)
    sent = float(getattr(strongest, "sentiment_score", 0.0) or 0.0) if strongest else 0.0

    # AVOID
    if score < AVOID_THRESHOLD:
        return "AVOID"
    if sent <= AVOID_NEWS_SENT:
        return "AVOID"

    # BUY_NOW
    if score >= STRONG_THRESHOLD and not chase:
        return "BUY_NOW"

    # STARTER
    if score >= STARTER_THRESHOLD and sent > STARTER_NEWS_SENT and not chase:
        return "STARTER"

    return "WAIT"


def _why_text(candidate, articles, *, decision: str, tag: str) -> str:
    """One-line institutional reason for the decision."""
    sym = _short_symbol(candidate.symbol)
    extras = getattr(candidate, "extras", None) or {}
    px = extras.get("px") or {}
    signals = getattr(candidate, "signals", None) or {}

    technical = signals.get("technical")
    cross_asset = signals.get("cross_asset")
    funding = signals.get("funding_rate")

    rsi = (getattr(technical, "details", {}) or {}).get("rsi14") if technical else None
    macd_label = ""
    if technical and technical.bullets:
        for b in technical.bullets:
            if "MACD" in b:
                macd_label = b.split(":")[0]
                break

    rs60 = None
    if cross_asset:
        rs60 = (getattr(cross_asset, "details", {}) or {}).get("rel_strength_60d")

    funding_8h = None
    if funding:
        details = getattr(funding, "details", {}) or {}
        funding_8h = details.get("median_8h") or details.get("most_recent_8h")

    strongest = _strongest_news(articles)
    headline = getattr(strongest, "title", None) if strongest else None
    sent = float(getattr(strongest, "sentiment_score", 0.0) or 0.0) if strongest else 0.0
    p5d = _five_day_return(px)
    p7d = px.get("p7d")

    if decision == "BUY_NOW":
        # Prefer the catalyst story.
        if strongest is not None and sent <= -POSITIVE_NEWS_SENT and p5d is not None and p5d <= DIP_5D:
            return "Negative-news dip looks priced in; setup is contrarian-bullish"
        if funding_8h is not None and funding_8h < -0.0002:
            return "Funding flipped negative on perps; forced selling exhausted"
        if rsi is not None and rsi <= 35:
            return f"RSI {rsi:.0f} oversold and trend signals firming"
        if rs60 is not None and rs60 >= 0.10:
            return f"{sym} outperforming BTC by {rs60 * 100:.0f}pt over 60d with score in STRONG"
        return "Composite signals firmed into STRONG with no chase warning"

    if decision == "STARTER":
        if headline:
            return f"Constructive 24h catalyst (sentiment {sent:+.2f}); start small until trend confirms"
        return "Score firming above 55 with positive tape; size as a starter"

    if decision == "AVOID":
        if sent <= -POSITIVE_NEWS_SENT and headline:
            return f"Fresh negative catalyst (sentiment {sent:+.2f}); thesis pending review"
        if rs60 is not None and rs60 <= -0.20:
            return f"{sym} underperforming BTC by {-rs60 * 100:.0f}pt over 60d"
        if "death" in (macd_label or "").lower():
            return "Death cross active and breadth weak"
        return "Score below avoid threshold; no edge today"

    # WAIT
    if tag == "chase trap":
        return "Move already happened; post-chase drift typically negative for 7-10d"
    if tag == "at 60d peak":
        return "At 60d peak; wait for a 3-5% pullback before adding"
    if rsi is not None and rsi >= 70:
        return f"RSI {rsi:.0f} extended; wait for cooler print"
    if rs60 is not None and rs60 >= 0.10:
        return f"Outperforming BTC by {rs60 * 100:.0f}pt over 60d but score not in STRONG yet"
    if p7d is not None and p7d <= -0.05:
        return "7d weak; wait for stabilisation rather than catching the knife"
    return "Composite score in neutral cluster; no clear edge yet"


def _value_bullets(candidate, articles) -> list[str]:
    """2-4 institutional-voice supporting bullets, drawn from real signals.

    Skips bullets where data isn't available so we never pad."""
    out: list[str] = []
    sym = _short_symbol(candidate.symbol)
    signals = getattr(candidate, "signals", None) or {}

    cross_asset = signals.get("cross_asset")
    if cross_asset:
        details = getattr(cross_asset, "details", {}) or {}
        rs60 = details.get("rel_strength_60d")
        if rs60 is not None and abs(rs60) >= 0.05:
            verb = "Outperforming" if rs60 >= 0 else "Underperforming"
            out.append(f"{verb} BTC by {abs(rs60) * 100:.0f}pt over 60d")
        rs30 = details.get("rel_strength_30d")
        if rs30 is not None and abs(rs30) >= 0.05 and len(out) < 2:
            verb = "Leading" if rs30 >= 0 else "Lagging"
            out.append(f"{verb} BTC by {abs(rs30) * 100:.0f}pt over 30d")

    funding = signals.get("funding_rate")
    if funding:
        details = getattr(funding, "details", {}) or {}
        f8 = details.get("median_8h") or details.get("most_recent_8h")
        if f8 is not None:
            if f8 <= -0.0002:
                out.append(f"Funding rate {f8 * 100:+.3f}% per 8h: contrarian bullish")
            elif f8 >= 0.0005:
                out.append(f"Funding rate {f8 * 100:+.3f}% per 8h: leverage-heavy, fade")

    extras = getattr(candidate, "extras", None) or {}
    oi_today = extras.get("oi_today")
    oi_7d = extras.get("oi_7d_ago")
    if oi_today and oi_7d and oi_7d > 0:
        chg = oi_today / oi_7d - 1.0
        if abs(chg) >= 0.10:
            verb = "up" if chg >= 0 else "down"
            out.append(f"OI {verb} {abs(chg) * 100:.0f}% week-on-week")

    onchain = signals.get("onchain")
    if onchain and getattr(onchain, "bullets", None):
        # Pick the first concrete on-chain bullet.
        for b in onchain.bullets:
            if "active addresses" in b.lower() or "netflow" in b.lower():
                out.append(b)
                break

    technical = signals.get("technical")
    if technical:
        details = getattr(technical, "details", {}) or {}
        rsi = details.get("rsi14")
        if rsi is not None and (rsi <= 30 or rsi >= 70):
            label = "oversold" if rsi <= 30 else "overbought"
            out.append(f"RSI {rsi:.0f} {label}")

    strongest = _strongest_news(articles)
    if strongest is not None and len(out) < 4:
        sent = float(getattr(strongest, "sentiment_score", 0.0) or 0.0)
        if abs(sent) >= 0.3:
            verb = "Positive" if sent > 0 else "Negative"
            out.append(f"{verb} 24h headline (sentiment {sent:+.2f})")

    if not out:
        # Make sure something supports the line; mention the symbol category.
        klass = classify(candidate.symbol)
        out.append(f"{sym} {klass.lower()}-tier name; price action in focus")
    return out[:4]


def _main_risk(candidate, articles) -> str:
    sym = _short_symbol(candidate.symbol)
    risk_obj = getattr(candidate, "risk", None)
    if risk_obj is not None and getattr(risk_obj, "warnings", None):
        for w in risk_obj.warnings:
            wl = w.lower()
            if "drawdown" in wl or "high realised vol" in wl or "portfolio drawdown" in wl:
                return w
    px = _px(candidate)
    p30d = px.get("p30d")
    if p30d is not None and p30d <= -0.20:
        return f"30d drawdown {p30d * 100:.0f}%: review thesis"
    risk_lookup = {
        "BTC": "ETF outflow risk if institutional bid fades",
        "ETH": "Pectra post-fork risk if validator activity drops",
        "SOL": "Validator concentration: top 10 control 38% of stake",
        "BNB": "Regulatory overhang on Binance Holdings entities",
        "XRP": "SEC appeal outcome could re-introduce regulatory risk",
        "ADA": "Light DeFi traction; momentum dependent on dev cadence",
        "AVAX": "Subnet adoption pace below schedule",
        "DOT": "Parachain auctions cooling: revenue narrative weak",
        "LINK": "Stable cash burn vs token unlocks creates supply pressure",
        "MATIC": "Migration to POL still incomplete; bridge tail risk",
        "POL": "Migration to POL still incomplete; bridge tail risk",
    }
    return risk_lookup.get(sym, f"Stablecoin de-peg risk if USDT < $0.997")


def _technical_summary(candidate) -> str:
    signals = getattr(candidate, "signals", None) or {}
    tech = signals.get("technical")
    cross = signals.get("cross_asset")
    parts: list[str] = []
    if tech:
        details = getattr(tech, "details", {}) or {}
        rsi = details.get("rsi14")
        if rsi is not None:
            parts.append(f"RSI {rsi:.0f}")
        macd = details.get("macd")
        if macd and isinstance(macd, dict):
            macd_line = macd.get("line")
            sig_line = macd.get("signal")
            if macd_line is not None and sig_line is not None:
                if macd_line > sig_line and macd_line > 0:
                    parts.append("MACD bullish")
                elif macd_line < sig_line and macd_line < 0:
                    parts.append("MACD bearish")
                elif macd_line > sig_line:
                    parts.append("MACD turning up")
                else:
                    parts.append("MACD turning down")
        cx = details.get("ema_cross")
        if cx == "golden":
            parts.append("golden cross 20/50")
        elif cx == "death":
            parts.append("death cross 20/50")
    if cross:
        details = getattr(cross, "details", {}) or {}
        rs60 = details.get("rel_strength_60d")
        if rs60 is not None:
            verb = "vs BTC +" if rs60 >= 0 else "vs BTC "
            parts.append(f"{verb}{rs60 * 100:.0f}pt 60d")
    if not parts:
        return "Technicals neutral / insufficient history"
    return "; ".join(parts)


def _price_targets(px: dict) -> dict[str, float | None]:
    """ATR-based price targets matching the spec.

    buy_zone = (last - 0.5*atr, last - 0.1*atr)
    buy_if_price = last - 0.8*atr
    max_chase = last + 0.5*atr
    sell_half = last + 1.0*atr
    sell_quarter = last + 2.0*atr
    stop = last - 1.5*atr
    """
    out = {
        "buy_if": None, "buy_zone_lo": None, "buy_zone_hi": None,
        "max_chase": None, "sell_half": None, "sell_quarter": None,
        "stop": None, "target_base": None, "target_bull": None,
    }
    last = px.get("last")
    atr = px.get("atr14")
    if last is None or atr is None or atr <= 0:
        return out
    out["buy_if"] = last - 0.8 * atr
    out["buy_zone_lo"] = last - 0.5 * atr
    out["buy_zone_hi"] = last - 0.1 * atr
    out["max_chase"] = last + 0.5 * atr
    out["sell_half"] = last + 1.0 * atr
    out["sell_quarter"] = last + 2.0 * atr
    out["stop"] = last - 1.5 * atr
    out["target_base"] = out["sell_half"]
    out["target_bull"] = out["sell_quarter"]
    return out


def _break_thesis(candidate, *, decision: str) -> str:
    sym = _short_symbol(candidate.symbol)
    if sym == "BTC":
        return "BTC drops 8% from here OR ETH/BTC ratio breaks 0.030 floor"
    if sym == "ETH":
        return "ETH/BTC rolls over below 0.030 OR BTC > $80k with ETH flat"
    if decision == "BUY_NOW":
        return "Total mcap drops 8% from here OR BTC breaks 7d low"
    if decision == "STARTER":
        return "Funding rate flips strongly positive (>0.05% per 8h)"
    if decision == "AVOID":
        return "Score climbs back above 50 AND positive catalyst confirms"
    return f"{sym} fails to reclaim its 30d high in the next 14d"


def _review_days(decision: str, tag: str) -> int:
    if "breaking" in tag or tag == "material event":
        return 5
    if decision == "WAIT":
        return 14
    return 7


def _suggested_size(decision: str, score: float, total_book_usd: float = 5000.0) -> float | None:
    """Position-size for the paper book.

    BUY_NOW: $1000 (score 65-80) -> $1500 (score 80+).
    STARTER: $500.
    WAIT/AVOID: None.
    """
    if decision == "BUY_NOW":
        return 1500.0 if score >= 80 else 1000.0
    if decision == "STARTER":
        return 500.0
    return None


def build_decision(
    candidate,
    *,
    articles: list | None = None,
    total_book_usd: float = 5000.0,
) -> CandidateDecision:
    """Compute a full CandidateDecision for one Candidate.

    ``articles`` is the per-symbol news list (24h window). Pass [] when no
    news is available.
    """
    articles = articles or []
    klass = classify(candidate.symbol)
    tag = pick_tag(candidate, articles)
    decision = pick_decision(candidate, articles, tag=tag)
    why = _why_text(candidate, articles, decision=decision, tag=tag)
    bullets = _value_bullets(candidate, articles)
    main_risk = _main_risk(candidate, articles)
    technical_summary = _technical_summary(candidate)
    px = _px(candidate)
    targets = _price_targets(px)
    review = _review_days(decision, tag)
    break_if = _break_thesis(candidate, decision=decision)
    size = _suggested_size(decision, float(getattr(candidate, "score", 0.0) or 0.0), total_book_usd)

    buy_zone = None
    if targets["buy_zone_lo"] is not None and targets["buy_zone_hi"] is not None:
        buy_zone = (float(targets["buy_zone_lo"]), float(targets["buy_zone_hi"]))

    return CandidateDecision(
        classification=klass,
        decision=decision,
        tag=tag,
        why_text=why,
        value_bullets=bullets,
        main_risk=main_risk,
        technical_summary=technical_summary,
        buy_if_price=targets["buy_if"],
        buy_zone=buy_zone,
        max_chase=targets["max_chase"],
        sell_half_price=targets["sell_half"],
        sell_quarter_price=targets["sell_quarter"],
        stop_price=targets["stop"],
        target_base=targets["target_base"],
        target_bull=targets["target_bull"],
        review_in_days=review,
        break_thesis_if=break_if,
        suggested_size_usd=size,
    )


def attach_decisions(
    candidates,
    *,
    news_by_symbol: dict[str, list] | None = None,
    total_book_usd: float = 5000.0,
) -> None:
    """Mutate every Candidate, attaching ``extras['decision']`` (a dict)."""
    news_by_symbol = news_by_symbol or {}
    for c in candidates:
        articles = _news_for_symbol(c.symbol, news_by_symbol)
        d = build_decision(c, articles=articles, total_book_usd=total_book_usd)
        if c.extras is None:
            c.extras = {}
        c.extras["decision"] = d.to_dict()
