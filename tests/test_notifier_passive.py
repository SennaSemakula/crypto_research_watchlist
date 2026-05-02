"""Tests for the passive Telegram notifier."""

from __future__ import annotations

from unittest.mock import MagicMock

from crypto_research_watchlist.autotrader.passive import (
    PassiveAction,
    PassiveDecision,
    PassiveReport,
)
from crypto_research_watchlist.notifiers.passive_notifier import (
    format_report,
    send_passive_telegram,
)


def _decision(
    action=PassiveAction.AUTO_BUY_SHADOW, symbol="BTC-USD", score=0.6,
    tranche=100.0, hc=True, reasons=None,
):
    return PassiveDecision(
        action=action, symbol=symbol,
        tranche_usd=tranche, quantity=0.0011,
        accumulation_score=score, high_conviction=hc,
        reasons=reasons or ["score 0.60 >= floor", "tranche $100"],
    )


def test_empty_report_returns_empty_string():
    assert format_report(PassiveReport()) == ""


def test_no_actionable_returns_empty_string():
    report = PassiveReport(decisions=[
        _decision(action=PassiveAction.HOLD),
        _decision(action=PassiveAction.WAIT_FOR_BETTER_PRICE),
        _decision(action=PassiveAction.DO_NOT_BUY),
    ])
    assert format_report(report) == ""


def test_actionable_renders_message_with_header():
    report = PassiveReport(
        decisions=[_decision()], shadow_mode=True,
    )
    text = format_report(report)
    assert "CRYPTO AUTO-INVESTOR [SHADOW]" in text
    assert "BTC-USD" in text
    assert "AUTO_BUY_SHADOW" in text
    assert "tranche" in text or "$100" in text


def test_html_special_chars_are_escaped():
    report = PassiveReport(
        decisions=[_decision(reasons=["a < b & c > d"])],
        shadow_mode=True,
    )
    text = format_report(report)
    assert "&lt;" in text
    assert "&amp;" in text
    assert "<reasons>" not in text


def test_truncation_at_4000_chars():
    longish = "x" * 60
    decisions = [
        _decision(reasons=[longish] * 50) for _ in range(60)
    ]
    report = PassiveReport(decisions=decisions, shadow_mode=True)
    text = format_report(report)
    assert len(text) <= 4100  # 4000 + truncated marker
    assert "truncated" in text or len(text) <= 4000


def test_send_passive_telegram_with_mock_http(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "abc")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "123")
    monkeypatch.setenv("TELEGRAM_ENABLED", "true")
    report = PassiveReport(
        decisions=[_decision()], shadow_mode=True,
    )
    http = MagicMock()
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    http.post = MagicMock(return_value=resp)
    ok = send_passive_telegram(report, http=http)
    assert ok is True
    http.post.assert_called_once()
    payload = http.post.call_args.kwargs["json"]
    assert payload["chat_id"] == "123"
    assert payload["parse_mode"] == "HTML"


def test_send_skipped_when_disabled(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "abc")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "123")
    monkeypatch.setenv("TELEGRAM_ENABLED", "false")
    report = PassiveReport(
        decisions=[_decision()], shadow_mode=True,
    )
    http = MagicMock()
    ok = send_passive_telegram(report, http=http)
    assert ok is False
    http.post.assert_not_called()


def test_daily_mode_never_quiet_with_no_actionable():
    """daily_mode forces a message even when nothing is actionable."""
    report = PassiveReport(decisions=[
        _decision(action=PassiveAction.WAIT_FOR_BETTER_PRICE, symbol="BTC-USD", score=45.0),
        _decision(action=PassiveAction.DO_NOT_BUY, symbol="ETH-USD", score=30.0),
    ])
    text = format_report(report, daily_mode=True)
    assert text != ""
    assert "0 buys" in text or "below buy floor" in text
    assert "BTC-USD" in text


def test_daily_mode_actionable_still_renders():
    """daily_mode does not change the actionable path."""
    report = PassiveReport(decisions=[_decision()], shadow_mode=True)
    text = format_report(report, daily_mode=True)
    assert "CRYPTO AUTO-INVESTOR" in text
    assert "BTC-USD" in text


def test_send_skipped_without_creds(monkeypatch):
    # _clean_env fixture clears these, so explicit unset.
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    report = PassiveReport(
        decisions=[_decision()], shadow_mode=True,
    )
    http = MagicMock()
    ok = send_passive_telegram(report, http=http)
    assert ok is False
    http.post.assert_not_called()
