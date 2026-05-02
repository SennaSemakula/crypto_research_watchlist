"""VADER-based sentiment scorer with crypto keyword booster.

Produces a (-1..+1) compound score and a coarse label
(positive / neutral / negative). The crypto booster nudges the score for
unambiguous crypto-specific terms VADER does not weight well.

The NLTK lexicon download is best-effort: we try at first use and fall
back to a tiny built-in keyword scorer when the lexicon is unavailable.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass

logger = logging.getLogger(__name__)


# Negative crypto-specific terms VADER misses or under-weights.
_CRYPTO_NEG = {
    "exploit": -0.4,
    "hack": -0.4,
    "hacked": -0.4,
    "delisted": -0.35,
    "delist": -0.3,
    "lawsuit": -0.3,
    "fud": -0.2,
    "dump": -0.25,
    "rugpull": -0.5,
    "rug pull": -0.5,
    "bankruptcy": -0.5,
    "bankrupt": -0.45,
    "ban": -0.25,
    "sec sues": -0.4,
    "fraud": -0.4,
    "depeg": -0.35,
    "de-peg": -0.35,
    "liquidated": -0.25,
    "scam": -0.4,
    "crash": -0.3,
    "drops": -0.15,
    "tumbles": -0.25,
    "plunges": -0.3,
}

_CRYPTO_POS = {
    "etf": 0.35,
    "etf approval": 0.5,
    "approval": 0.25,
    "approved": 0.25,
    "rally": 0.25,
    "adopt": 0.25,
    "adoption": 0.25,
    "partnership": 0.2,
    "upgrade": 0.2,
    "upgraded": 0.2,
    "listing": 0.25,
    "listed": 0.2,
    "all time high": 0.4,
    "ath": 0.3,
    "breakout": 0.25,
    "surge": 0.25,
    "surges": 0.25,
    "soars": 0.3,
    "rallies": 0.3,
    "milestone": 0.2,
}


@dataclass(slots=True)
class SentimentResult:
    score: float           # in [-1, +1]
    label: str             # positive / neutral / negative
    components: dict       # debug detail


_lock = threading.Lock()
_vader_singleton = None
_vader_unavailable = False


def _get_vader():
    """Lazily load NLTK VADER. Best-effort lexicon download."""
    global _vader_singleton, _vader_unavailable
    if _vader_singleton is not None:
        return _vader_singleton
    if _vader_unavailable:
        return None
    with _lock:
        if _vader_singleton is not None:
            return _vader_singleton
        if _vader_unavailable:
            return None
        try:
            import nltk
            from nltk.sentiment import SentimentIntensityAnalyzer
            try:
                _vader_singleton = SentimentIntensityAnalyzer()
                return _vader_singleton
            except LookupError:
                # Lexicon not installed; try downloading.
                try:
                    nltk.download("vader_lexicon", quiet=True)
                    _vader_singleton = SentimentIntensityAnalyzer()
                    return _vader_singleton
                except Exception as exc:
                    logger.info("VADER lexicon unavailable: %s", exc)
                    _vader_unavailable = True
                    return None
        except Exception as exc:
            logger.info("NLTK SentimentIntensityAnalyzer unavailable: %s", exc)
            _vader_unavailable = True
            return None


def _crypto_boost(text_lower: str) -> tuple[float, list[str]]:
    """Sum keyword boosts and return (score_delta, hit_terms)."""
    delta = 0.0
    hits: list[str] = []
    for term, weight in _CRYPTO_NEG.items():
        if term in text_lower:
            delta += weight
            hits.append(term)
    for term, weight in _CRYPTO_POS.items():
        if term in text_lower:
            delta += weight
            hits.append(term)
    # Clip booster to [-0.6, +0.6] so a single article cannot dominate.
    delta = max(-0.6, min(0.6, delta))
    return delta, hits


def _fallback_score(text_lower: str) -> tuple[float, list[str]]:
    """Tiny keyword-only scorer when VADER unavailable. Same booster."""
    return _crypto_boost(text_lower)


def label_from_score(score: float) -> str:
    if score >= 0.15:
        return "positive"
    if score <= -0.15:
        return "negative"
    return "neutral"


def score_text(text: str) -> SentimentResult:
    """Score a headline + body fragment. Returns SentimentResult.

    Empty / None input returns neutral 0.0.
    """
    if not text:
        return SentimentResult(score=0.0, label="neutral", components={"reason": "empty"})

    lower = text.lower()
    boost, hits = _crypto_boost(lower)
    vader = _get_vader()
    if vader is None:
        score = boost
        return SentimentResult(
            score=score,
            label=label_from_score(score),
            components={"vader": None, "boost": boost, "hits": hits},
        )

    try:
        sc = vader.polarity_scores(text)
        compound = float(sc.get("compound", 0.0))
    except Exception as exc:
        logger.debug("VADER scoring failed: %s", exc)
        compound = 0.0
        sc = {}

    raw = compound + boost
    score = max(-1.0, min(1.0, raw))
    return SentimentResult(
        score=score,
        label=label_from_score(score),
        components={"vader": sc, "boost": boost, "hits": hits, "raw": raw},
    )
