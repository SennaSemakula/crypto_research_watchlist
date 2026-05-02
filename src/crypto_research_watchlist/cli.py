"""Typer CLI: thin wrapper over the pipeline.

Subcommands:
  init-db           Create the SQLite schema (idempotent).
  run               Run the pipeline once and write a markdown watchlist.
  candidates        Print the latest run's ranked candidates to stdout.
  paper-status      Show paper portfolio cash + positions.
  passive           Run the passive accumulation engine, optionally Telegram.
  aggressive        Run the aggressive rotation engine, optionally Telegram.
  supervise         Reconcile paper-broker state with system state.
  learning-summary  Weekly digest of decisions + back-evaluated hit rate.
"""

from __future__ import annotations

import logging

import typer

from .config import EnvSettings, load_app_config
from .db import init_db, session_factory, session_scope
from .models import CandidateRecord, PaperCash, PaperPosition
from .pipeline import run_once

app = typer.Typer(add_completion=False, no_args_is_help=True)


@app.command("init-db")
def cli_init_db() -> None:
    """Create the SQLite schema."""
    env = EnvSettings.from_env()
    init_db(env.database_url)
    typer.echo(f"db ready at {env.database_url}")


@app.command("run")
def cli_run(
    write_report: bool = True,
    persist: bool = True,
    send_telegram: bool = typer.Option(False, "--send-telegram", help="Send the ranked watchlist to Telegram. Requires TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID + TELEGRAM_ENABLED in env."),
) -> None:
    """Run the pipeline once."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    for noisy in ("httpx", "httpcore", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    cfg = load_app_config()
    env = EnvSettings.from_env()
    engine = init_db(env.database_url) if persist else None
    result = run_once(cfg=cfg, engine=engine, write_report=write_report)
    top = result.candidates[: cfg.reports.top_n_terminal]
    typer.echo(f"run_at={result.run_at.isoformat()}")
    for idx, c in enumerate(top, 1):
        typer.echo(f"{idx:2d}. {c.symbol:10s} {c.action:8s} {c.score:+.2f}  {c.reason}")
    if result.report_path:
        typer.echo(f"report: {result.report_path}")

    if send_telegram:
        from .notifiers.telegram import TelegramNotifier
        cfg.notifications.telegram = True
        outcome = TelegramNotifier(cfg, env).send(result)
        typer.echo(f"telegram: status={outcome.status} error={outcome.error or '-'}")
        if outcome.status in {"failed", "partial"}:
            raise typer.Exit(code=1)


@app.command("candidates")
def cli_candidates(limit: int = 10) -> None:
    """Print the latest persisted run's ranking."""
    env = EnvSettings.from_env()
    engine = init_db(env.database_url)
    SessionLocal = session_factory(engine)
    from sqlalchemy import desc, select
    with session_scope(SessionLocal) as session:
        latest_run = session.scalars(
            select(CandidateRecord.run_at).order_by(desc(CandidateRecord.run_at)).limit(1)
        ).first()
        if latest_run is None:
            typer.echo("no candidates yet")
            return
        rows = session.scalars(
            select(CandidateRecord)
            .where(CandidateRecord.run_at == latest_run)
            .order_by(desc(CandidateRecord.score))
            .limit(limit)
        ).all()
        for r in rows:
            typer.echo(f"{r.symbol:10s} {r.action:8s} {r.score:+.2f}  {r.reason}")


@app.command("paper-status")
def cli_paper_status() -> None:
    """Show paper portfolio cash + positions."""
    env = EnvSettings.from_env()
    engine = init_db(env.database_url)
    SessionLocal = session_factory(engine)
    from sqlalchemy import select
    with session_scope(SessionLocal) as session:
        cash = session.get(PaperCash, 1)
        positions = list(session.scalars(select(PaperPosition)).all())
        typer.echo(f"cash: ${(cash.cash_usd if cash else 0):,.2f}")
        if not positions:
            typer.echo("no positions")
            return
        for p in positions:
            if p.quantity == 0:
                continue
            typer.echo(f"{p.symbol:10s} qty={p.quantity:.6f} avg=${p.avg_price:.2f} realised=${p.realised_pnl:.2f}")


@app.command("passive")
def cli_passive(
    send_telegram: bool = typer.Option(False, "--send-telegram", help="POST report to Telegram."),
) -> None:
    """Run the passive accumulation engine on the latest pipeline result."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    cfg = load_app_config()
    env = EnvSettings.from_env()
    engine = init_db(env.database_url)
    result = run_once(cfg=cfg, engine=engine, write_report=False)

    from .autotrader.passive import run_once_passive
    from .autotrader.paper_broker import PaperBroker

    def _quote(symbol: str) -> float | None:
        for c in result.candidates:
            if c.symbol == symbol:
                px = (c.extras.get("px") or {}) if c.extras else {}
                return px.get("last")
        return None

    broker = PaperBroker(
        engine=engine, quote_fn=_quote,
        starting_cash=cfg.portfolio.cash_available_usd,
    )
    report = run_once_passive(engine=engine, cfg=cfg, run_result=result, broker=broker)
    typer.echo(
        f"passive: {len(report.decisions)} decision(s) "
        f"(buys={report.buys_placed} adds={report.add_tranches_placed} "
        f"shadow={report.shadow_buys} blocked={report.blocked} "
        f"errors={report.errors})"
    )
    for d in report.decisions:
        size = f" ${d.tranche_usd:.2f}" if d.tranche_usd else ""
        typer.echo(
            f"  {d.action.value:24s} {d.symbol:10s} score={d.accumulation_score:+.2f}{size}"
        )
    if send_telegram:
        from .notifiers.passive_notifier import send_passive_telegram
        ok = send_passive_telegram(report)
        typer.echo(f"telegram: {'sent' if ok else 'skipped'}")


@app.command("aggressive")
def cli_aggressive(
    held_symbol: str = typer.Option(None, "--held-symbol"),
    held_rank_at_entry: int = typer.Option(None, "--held-rank-at-entry"),
    send_telegram: bool = typer.Option(False, "--send-telegram"),
) -> None:
    """Run the aggressive rotation engine."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    cfg = load_app_config()
    env = EnvSettings.from_env()
    engine = init_db(env.database_url)
    result = run_once(cfg=cfg, engine=engine, write_report=False)

    from .autotrader.aggressive import run_once_aggressive

    report = run_once_aggressive(
        engine=engine, cfg=cfg.crypto, run_result=result,
        held_symbol=held_symbol, held_rank_at_entry=held_rank_at_entry,
    )
    typer.echo(f"aggressive: {len(report.decisions)} decision(s)")
    for d in report.decisions:
        typer.echo(f"  {d.action.value:18s} {d.symbol:10s} score={d.score:+.2f}")
    if send_telegram:
        from .notifiers.aggressive_notifier import send_aggressive_telegram
        ok = send_aggressive_telegram(report, result)
        typer.echo(f"telegram: {'sent' if ok else 'skipped'}")


@app.command("supervise")
def cli_supervise(
    send_telegram: bool = typer.Option(False, "--send-telegram"),
    lookback_hours: int = typer.Option(48, "--lookback-hours"),
) -> None:
    """Reconcile paper-broker state with decision audit trail."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    env = EnvSettings.from_env()
    engine = init_db(env.database_url)
    cfg = load_app_config()

    from .autotrader.order_supervisor import format_supervisor_message, reconcile
    from .autotrader.paper_broker import PaperBroker

    broker = PaperBroker(
        engine=engine, quote_fn=lambda _s: None,
        starting_cash=cfg.portfolio.cash_available_usd,
    )
    report = reconcile(engine=engine, broker=broker, lookback_hours=lookback_hours)
    typer.echo(
        f"supervisor: cash=${report.cash_usd:,.2f} positions={report.positions_count} "
        f"reconciled={report.reconciled} mismatches={report.mismatches}"
    )
    for w in report.warnings:
        typer.echo(f"  {w}")
    if send_telegram and report.warnings:
        text = format_supervisor_message(report)
        if text:
            import os

            import httpx
            token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
            chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
            if token and chat_id and os.environ.get("TELEGRAM_ENABLED", "true").lower() not in ("false", "0", "no"):
                try:
                    httpx.post(
                        f"https://api.telegram.org/bot{token}/sendMessage",
                        json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
                        timeout=15.0,
                    ).raise_for_status()
                    typer.echo("telegram: sent")
                except Exception as exc:
                    typer.echo(f"telegram: failed: {exc}")


@app.command("learning-summary")
def cli_learning_summary(
    weeks_back: int = typer.Option(1, "--weeks-back"),
    send_telegram: bool = typer.Option(False, "--send-telegram"),
    write_markdown: bool = typer.Option(True, "--write-markdown/--no-write-markdown"),
) -> None:
    """Weekly digest of decisions + hit-rate back-evaluation."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    env = EnvSettings.from_env()
    engine = init_db(env.database_url)

    from .autotrader.learning_summary import (
        build_weekly_summary,
        persist_summary,
        send_learning_telegram,
        write_markdown_report,
    )

    summary = build_weekly_summary(engine=engine, weeks_back=weeks_back)
    typer.echo(
        f"learning-summary: passive={sum(summary.passive_action_counts.values())} "
        f"aggressive={sum(summary.aggressive_action_counts.values())} "
        f"hit_rate={summary.hit_rate_pct} (n={summary.hit_rate_n})"
    )
    persist_summary(engine, summary)
    if write_markdown:
        path = write_markdown_report(summary)
        typer.echo(f"markdown: {path}")
    if send_telegram:
        ok = send_learning_telegram(summary)
        typer.echo(f"telegram: {'sent' if ok else 'skipped'}")


def main() -> None:
    app()


__all__ = ["app", "main"]


if __name__ == "__main__":  # pragma: no cover
    main()
