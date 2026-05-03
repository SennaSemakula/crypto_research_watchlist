"""Tests for the intraday scan + alert.

All offline. Mock httpx in notifier tests. Use frozen CandidateRecord rows
in an in-memory SQLite for engine tests.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest
from typer.testing import CliRunner

from crypto_research_watchlist.cli import app
from crypto_research_watchlist.notifiers.intraday_notifier import (
    IntradayAlert,
    NewsHit,
    ScoreMove,
    render_alert,
    send_intraday_telegram,
)


# ---------------------------------------------------------------------------
# Notifier render tests (pure)
# ---------------------------------------------------------------------------


def _alert_with_both() -> IntradayAlert:
    return IntradayAlert(
        score_moves=[
            ScoreMove(
                symbol="BTC-USD", prior_score=50.0, current_score=72.0,
                prior_action="WATCH", current_action="STRONG",
            ),
            ScoreMove(
                symbol="ETH-USD", prior_score=55.0, current_score=38.0,
                prior_action="WATCH", current_action="AVOID",
            ),
        ],
        news_hits=[
            NewsHit(symbol="BTC", title="SEC approves spot ETH ETF",
                    sentiment_score=0.85, sentiment_label="positive"),
            NewsHit(symbol="SOL", title="Major validator outage on mainnet",
                    sentiment_score=-0.78, sentiment_label="negative"),
        ],
        scanned_symbols=10,
        now=datetime(2026, 5, 2, 14, 0, tzinfo=timezone.utc),
    )


def test_intraday_notifier_renders_both_sections():
    text = render_alert(_alert_with_both())
    assert "Intraday alert" in text
    assert "Score moves" in text
    assert "BTC-USD" in text
    assert "ETH-USD" in text
    assert "STRONG" in text
    assert "New high-impact news" in text
    assert "ETF" in text
    assert "validator outage" in text
    assert "scanned 10 symbols" in text


def test_intraday_notifier_renders_one_section():
    only_news = IntradayAlert(
        score_moves=[],
        news_hits=[NewsHit(symbol="BTC", title="ETF approved",
                           sentiment_score=0.9, sentiment_label="positive")],
        scanned_symbols=8,
    )
    text = render_alert(only_news)
    assert "Intraday alert" in text
    assert "Score moves" not in text
    assert "New high-impact news" in text
    assert "scanned 8 symbols" in text

    only_scores = IntradayAlert(
        score_moves=[ScoreMove("BTC-USD", 50.0, 72.0, "WATCH", "STRONG")],
        news_hits=[],
        scanned_symbols=8,
    )
    text2 = render_alert(only_scores)
    assert "Score moves" in text2
    assert "New high-impact news" not in text2


def test_intraday_notifier_renders_empty_when_no_signal():
    alert = IntradayAlert(score_moves=[], news_hits=[], scanned_symbols=10)
    assert render_alert(alert) == ""


def test_intraday_notifier_escapes_html():
    alert = IntradayAlert(
        score_moves=[],
        news_hits=[NewsHit(
            symbol="BTC", title="<script>alert('xss')</script> & more",
            sentiment_score=0.6, sentiment_label="positive",
        )],
        scanned_symbols=1,
    )
    text = render_alert(alert)
    assert "<script>" not in text
    assert "&lt;script&gt;" in text
    assert "&amp;" in text


def test_intraday_notifier_send_skipped_when_disabled(monkeypatch):
    monkeypatch.setenv("TELEGRAM_ENABLED", "false")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "chat")
    http = MagicMock()
    ok = send_intraday_telegram(_alert_with_both(), http=http)
    assert ok is False
    http.post.assert_not_called()


def test_intraday_notifier_send_skipped_when_no_signal(monkeypatch):
    monkeypatch.setenv("TELEGRAM_ENABLED", "true")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "chat")
    http = MagicMock()
    ok = send_intraday_telegram(IntradayAlert(scanned_symbols=10), http=http)
    assert ok is False
    http.post.assert_not_called()


def test_intraday_notifier_send_posts_when_signal(monkeypatch):
    monkeypatch.setenv("TELEGRAM_ENABLED", "true")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "chat")
    http = MagicMock()
    http.post.return_value = MagicMock(status_code=200, raise_for_status=lambda: None)
    ok = send_intraday_telegram(_alert_with_both(), http=http)
    assert ok is True
    assert http.post.called
    payload = http.post.call_args.kwargs.get("json") or http.post.call_args[1]["json"]
    assert payload["parse_mode"] == "HTML"
    assert "Intraday alert" in payload["text"]


# ---------------------------------------------------------------------------
# CLI command tests (engine-backed)
# ---------------------------------------------------------------------------


@pytest.fixture()
def runner():
    return CliRunner()


def _seed_prior_candidate(engine, symbol: str, score: float, action: str, *,
                          when: datetime | None = None) -> None:
    from crypto_research_watchlist.db import session_factory, session_scope
    from crypto_research_watchlist.models import CandidateRecord

    SessionLocal = session_factory(engine)
    when = when or (datetime.now(timezone.utc) - timedelta(hours=1))
    with session_scope(SessionLocal) as session:
        session.add(CandidateRecord(
            run_at=when, symbol=symbol, action=action, score=score,
            reason="seed", payload={},
        ))


def _seed_news(engine, *, title: str, sentiment: float, currencies: list[str],
               minutes_ago: int) -> None:
    from crypto_research_watchlist.db import session_factory, session_scope
    from crypto_research_watchlist.models import NewsArticle

    SessionLocal = session_factory(engine)
    pub = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
    label = "positive" if sentiment > 0.2 else "negative" if sentiment < -0.2 else "neutral"
    with session_scope(SessionLocal) as session:
        session.add(NewsArticle(
            url=f"https://x.com/{title[:20]}-{minutes_ago}-{sentiment}",
            source="test", title=title, body=None, published_at=pub,
            currencies_json=currencies, sentiment_score=sentiment,
            sentiment_label=label, raw={},
        ))


def _set_env(monkeypatch, db_url: str) -> None:
    monkeypatch.setenv("DATABASE_URL", db_url)
    monkeypatch.delenv("TELEGRAM_ENABLED", raising=False)
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    # Drop optional API keys so the news refresh inside run_once stays
    # purely offline and these tests don't pick up live high-impact news.
    monkeypatch.delenv("CRYPTOCOMPARE_API_KEY", raising=False)
    monkeypatch.delenv("CRYPTOPANIC_API_KEY", raising=False)
    monkeypatch.delenv("ETHERSCAN_API_KEY", raising=False)


def test_intraday_no_prior_scores_does_not_alert(tmp_path, monkeypatch, runner):
    """First run, no baseline → no score deltas, telegram=skipped."""
    db = tmp_path / "intraday.db"
    db_url = f"sqlite:///{db}"
    _set_env(monkeypatch, db_url)

    sent: list[bool] = []

    def fake_send(alert, http=None):
        sent.append(True)
        return False

    monkeypatch.setattr(
        "crypto_research_watchlist.notifiers.intraday_notifier.send_intraday_telegram",
        fake_send,
    )

    res = runner.invoke(app, ["intraday", "--send-telegram"])
    assert res.exit_code == 0, res.output
    assert "0 score deltas" in res.output
    # No baseline → no signal, so telegram=skipped (we don't even call send).
    assert "telegram=skipped" in res.output
    assert sent == []


def test_intraday_score_delta_triggers_alert(tmp_path, monkeypatch, runner):
    """Prior 50 vs current ≥60 (delta ≥10) → alert fires."""
    db = tmp_path / "intraday.db"
    db_url = f"sqlite:///{db}"
    _set_env(monkeypatch, db_url)

    # Init schema and seed prior rows for every symbol the pipeline produces.
    from crypto_research_watchlist.db import init_db
    engine = init_db(db_url)

    # Seed extreme low priors so any current score will exceed the delta.
    from crypto_research_watchlist.config import load_app_config
    cfg = load_app_config()
    for sym in cfg.crypto.universe.symbols:
        _seed_prior_candidate(engine, sym, score=0.0, action="AVOID")

    captured: list[object] = []

    def fake_send(alert, http=None):
        captured.append(alert)
        return True

    monkeypatch.setattr(
        "crypto_research_watchlist.cli.send_intraday_telegram",
        fake_send,
        raising=False,
    )
    # Patch via the import location used inside cli_intraday.
    import crypto_research_watchlist.notifiers.intraday_notifier as nm
    monkeypatch.setattr(nm, "send_intraday_telegram", fake_send)

    res = runner.invoke(app, ["intraday", "--send-telegram", "--score-delta-threshold", "10"])
    assert res.exit_code == 0, res.output
    # Should have detected score deltas (current scores will be ≥10 vs prior 0).
    assert "telegram=sent" in res.output
    assert captured, "send_intraday_telegram was not called"
    alert = captured[0]
    assert alert.has_signal()
    assert any(m.delta >= 10 for m in alert.score_moves)


def test_intraday_action_change_triggers_alert(tmp_path, monkeypatch, runner):
    """Action flip triggers alert even when score delta < threshold."""
    db = tmp_path / "intraday.db"
    db_url = f"sqlite:///{db}"
    _set_env(monkeypatch, db_url)

    from crypto_research_watchlist.db import init_db
    engine = init_db(db_url)

    # Seed all symbols with the SAME current score they'll likely produce
    # but a different action — small delta, but action flipped.
    from crypto_research_watchlist.config import load_app_config
    cfg = load_app_config()
    # Pre-run the pipeline to see what scores/actions come out.
    from crypto_research_watchlist.pipeline import run_once
    pre = run_once(cfg=cfg, engine=engine, write_report=False)
    # Now tweak the seeded prior rows: same score, but flip action label.
    from crypto_research_watchlist.db import session_factory, session_scope
    from crypto_research_watchlist.models import CandidateRecord
    SessionLocal = session_factory(engine)
    # Wipe and reseed with flipped actions and identical scores.
    with session_scope(SessionLocal) as session:
        session.query(CandidateRecord).delete()
    for c in pre.candidates:
        flipped = "STRONG" if c.action != "STRONG" else "AVOID"
        _seed_prior_candidate(engine, c.symbol, score=c.score, action=flipped)

    captured: list[object] = []
    import crypto_research_watchlist.notifiers.intraday_notifier as nm
    monkeypatch.setattr(nm, "send_intraday_telegram",
                        lambda alert, http=None: (captured.append(alert), True)[1])

    res = runner.invoke(app, [
        "intraday", "--send-telegram", "--score-delta-threshold", "10000",
    ])
    assert res.exit_code == 0, res.output
    # Even with absurd score-delta threshold, action flip alone should fire.
    assert "telegram=sent" in res.output
    assert captured
    assert captured[0].score_moves


def test_intraday_high_impact_news_triggers_alert(tmp_path, monkeypatch, runner):
    """An article with |sentiment| ≥ 0.5 in last hour triggers alert."""
    db = tmp_path / "intraday.db"
    db_url = f"sqlite:///{db}"
    _set_env(monkeypatch, db_url)

    from crypto_research_watchlist.db import init_db
    engine = init_db(db_url)

    # Pre-seed prior candidates so score deltas don't fire (current ≈ prior).
    from crypto_research_watchlist.config import load_app_config
    cfg = load_app_config()
    from crypto_research_watchlist.pipeline import run_once
    pre = run_once(cfg=cfg, engine=engine, write_report=False)
    # Reseed prior with same scores AND same actions so neither score nor
    # action triggers.
    from crypto_research_watchlist.db import session_factory, session_scope
    from crypto_research_watchlist.models import CandidateRecord
    SessionLocal = session_factory(engine)
    with session_scope(SessionLocal) as session:
        session.query(CandidateRecord).delete()
    for c in pre.candidates:
        _seed_prior_candidate(engine, c.symbol, score=c.score, action=c.action)

    # Seed a high-impact article.
    _seed_news(engine, title="ETF approval ignites rally",
               sentiment=0.85, currencies=["BTC"], minutes_ago=10)

    captured: list[object] = []
    import crypto_research_watchlist.notifiers.intraday_notifier as nm
    monkeypatch.setattr(nm, "send_intraday_telegram",
                        lambda alert, http=None: (captured.append(alert), True)[1])

    res = runner.invoke(app, ["intraday", "--send-telegram"])
    assert res.exit_code == 0, res.output
    assert "1 new high-impact" in res.output or "1 new high-impact articles" in res.output
    assert "telegram=sent" in res.output
    assert captured
    assert captured[0].news_hits


def test_intraday_quiet_when_no_change(tmp_path, monkeypatch, runner):
    """No score moves AND no fresh news → no Telegram fired."""
    db = tmp_path / "intraday.db"
    db_url = f"sqlite:///{db}"
    _set_env(monkeypatch, db_url)

    from crypto_research_watchlist.db import init_db
    engine = init_db(db_url)

    from crypto_research_watchlist.config import load_app_config
    cfg = load_app_config()
    from crypto_research_watchlist.pipeline import run_once
    pre = run_once(cfg=cfg, engine=engine, write_report=False)
    from crypto_research_watchlist.db import session_factory, session_scope
    from crypto_research_watchlist.models import CandidateRecord
    SessionLocal = session_factory(engine)
    with session_scope(SessionLocal) as session:
        session.query(CandidateRecord).delete()
    for c in pre.candidates:
        _seed_prior_candidate(engine, c.symbol, score=c.score, action=c.action)

    captured: list[object] = []
    import crypto_research_watchlist.notifiers.intraday_notifier as nm
    monkeypatch.setattr(nm, "send_intraday_telegram",
                        lambda alert, http=None: (captured.append(alert), True)[1])

    res = runner.invoke(app, ["intraday", "--send-telegram"])
    assert res.exit_code == 0, res.output
    assert "0 score deltas" in res.output
    assert "0 new high-impact" in res.output
    assert "telegram=skipped" in res.output
    assert captured == []
