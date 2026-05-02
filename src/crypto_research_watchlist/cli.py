"""Typer CLI: thin wrapper over the pipeline.

Subcommands:
  init-db       Create the SQLite schema (idempotent).
  run           Run the pipeline once and write a markdown watchlist.
  candidates    Print the latest run's ranked candidates to stdout.
  paper-status  Show paper portfolio cash + positions.
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
def cli_run(write_report: bool = True, persist: bool = True) -> None:
    """Run the pipeline once."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
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


def main() -> None:
    app()


__all__ = ["app", "main"]


if __name__ == "__main__":  # pragma: no cover
    main()
