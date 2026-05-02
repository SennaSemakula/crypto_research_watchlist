"""Tests for news.sentiment scorer."""

from __future__ import annotations

from crypto_research_watchlist.news.sentiment import label_from_score, score_text


def test_score_neutral_for_empty():
    r = score_text("")
    assert r.score == 0.0
    assert r.label == "neutral"


def test_score_negative_for_hack_headline():
    r = score_text("Major exchange hacked: $100M stolen, exploit confirmed")
    assert r.score < -0.2
    assert r.label == "negative"


def test_score_positive_for_etf_approval():
    r = score_text("Spot Bitcoin ETF approval rallies BTC to all time high")
    assert r.score > 0.2
    assert r.label == "positive"


def test_label_from_score_thresholds():
    assert label_from_score(0.5) == "positive"
    assert label_from_score(0.0) == "neutral"
    assert label_from_score(-0.5) == "negative"
    assert label_from_score(0.14) == "neutral"
    assert label_from_score(-0.14) == "neutral"
