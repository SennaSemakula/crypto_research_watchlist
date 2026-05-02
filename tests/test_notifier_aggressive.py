"""Tests for the aggressive Telegram notifier."""

from __future__ import annotations

from dataclasses import dataclass, field
from unittest.mock import MagicMock

from crypto_research_watchlist.autotrader.aggressive import (
    AggressiveAction,
    AggressiveDecision,
    AggressiveReport,
)
from crypto_research_watchlist.notifiers.aggressive_notifier import (
    format_report,
    send_aggressive_telegram,
)


@dataclass
class _StubCandidate:
    symbol: str
    score: float
    action: str
    extras: dict = field(default_factory=dict)
    signals: dict = field(default_factory=dict)
    reason: str = ""


@dataclass
class _StubResult:
    candidates: list


def _decision(action=AggressiveAction.BUY, symbol="BTC-USD", score=0.6, reasons=None):
    return AggressiveDecision(
        action=action, symbol=symbol, score=score,
        prior_action="STRONG", reasons=reasons or ["top candidate"],
    )


def test_empty_report_returns_empty_string():
    assert format_report(AggressiveReport()) == ""


def test_no_actionable_returns_empty_string():
    report = AggressiveReport(decisions=[
        _decision(action=AggressiveAction.HOLD),
        _decision(action=AggressiveAction.AVOID),
    ])
    assert format_report(report) == ""


def test_buy_decision_renders_with_zones():
    candidate = _StubCandidate(
        symbol="BTC-USD", score=0.6, action="STRONG",
        extras={"px": {"last": 100.0, "atr14": 4.0, "p1d": 0.01, "p7d": 0.05}},
    )
    result = _StubResult(candidates=[candidate])
    report = AggressiveReport(decisions=[_decision()])
    text = format_report(report, result)
    assert "CRYPTO AGGRESSIVE ROTATION" in text
    assert "BTC-USD" in text
    assert "buy" in text or "BUY" in text
    assert "tp" in text  # ATR zones
    assert "stop" in text


def test_html_escapes_special_chars():
    report = AggressiveReport(decisions=[
        _decision(reasons=["danger < 1 & y"]),
    ])
    text = format_report(report)
    assert "&lt;" in text
    assert "&amp;" in text


def test_truncation_at_4000_chars():
    long_reason = "x" * 80
    decisions = [
        _decision(reasons=[long_reason] * 10) for _ in range(60)
    ]
    report = AggressiveReport(decisions=decisions)
    text = format_report(report)
    assert len(text) <= 4100


def test_send_with_mock_http(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "abc")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "123")
    monkeypatch.setenv("TELEGRAM_ENABLED", "true")
    report = AggressiveReport(decisions=[_decision()])
    http = MagicMock()
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    http.post = MagicMock(return_value=resp)
    ok = send_aggressive_telegram(report, http=http)
    assert ok is True


def test_send_skipped_when_disabled(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "abc")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "123")
    monkeypatch.setenv("TELEGRAM_ENABLED", "false")
    report = AggressiveReport(decisions=[_decision()])
    http = MagicMock()
    ok = send_aggressive_telegram(report, http=http)
    assert ok is False
    http.post.assert_not_called()
