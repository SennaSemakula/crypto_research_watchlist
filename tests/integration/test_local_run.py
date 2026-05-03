"""Local end-to-end smoke run.

Skipped by default. Run explicitly to fire a real Telegram with the
upgraded news + on-chain stack:

    pytest -m integration tests/integration/test_local_run.py -s

Requires .env keys to be present; gracefully skips if Telegram or
the new-source keys aren't set. Captures the news refresh log lines
so the operator can confirm CryptoCompare counts.
"""

from __future__ import annotations

import logging
import os

import pytest

pytestmark = pytest.mark.integration


def test_pipeline_run_with_telegram(caplog):
    # Eager-load .env so we pick up keys when invoked outside the CLI.
    try:
        from dotenv import load_dotenv
        from pathlib import Path
        load_dotenv(Path(__file__).resolve().parents[2] / ".env", override=False)
    except Exception:
        pass

    if not (
        os.environ.get("TELEGRAM_BOT_TOKEN")
        and os.environ.get("TELEGRAM_CHAT_ID")
        and os.environ.get("CRYPTOCOMPARE_API_KEY")
    ):
        pytest.skip("missing TELEGRAM_* or CRYPTOCOMPARE_API_KEY")

    from crypto_research_watchlist.config import EnvSettings, load_app_config
    from crypto_research_watchlist.db import init_db
    from crypto_research_watchlist.news.orchestrator import refresh_news
    from crypto_research_watchlist.pipeline import run_once

    cfg = load_app_config()
    env = EnvSettings.from_env()
    engine = init_db(env.database_url)

    caplog.set_level(logging.INFO, logger="crypto_research_watchlist.news.orchestrator")
    caplog.set_level(logging.INFO, logger="crypto_research_watchlist.news.sources")

    report = refresh_news(engine, cfg.crypto)
    print("\nNEWS REFRESH BY SOURCE:", report.by_source)
    print("NEWS REFRESH inserted=%s skipped=%s" % (report.inserted, report.skipped))

    # CryptoCompare must show up; >0 indicates the new pipe is live.
    assert "cryptocompare" in report.by_source

    # Run the full pipeline. Telegram send below uses the candidates.
    result = run_once(cfg=cfg, engine=engine, refresh_news=False, write_report=False)
    print("PIPELINE candidates=%d" % len(result.candidates))

    cfg.notifications.telegram = True
    from crypto_research_watchlist.notifiers.telegram import TelegramNotifier
    outcome = TelegramNotifier(cfg, env, engine=engine).send(result)
    print(f"MARKER_TELEGRAM_RESULT status={outcome.status} error={outcome.error or '-'}")
    assert outcome.status in {"sent", "skipped"}  # both acceptable
