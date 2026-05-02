"""Weekly learning summary — what the crypto loop did and how it learned.

Computed from the decision tables (passive_decisions + aggressive_decisions)
and the parquet historical OHLCV. Reports:
  * Decisions per action this week (counts).
  * Hit-rate proxy: of WATCH+ candidates 7 days ago, what % moved positively
    in the next 7 days. Back-evaluated from the parquet so it works offline.
  * Score distribution shift week-over-week (mean / median).
  * Top decisions ranked by realised price move 7d later.

Renders to:
  * a Telegram-ready string
  * a markdown report at reports/learning_summary_<date>.md
"""

from __future__ import annotations

import html
import logging
import os
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[3]


@dataclass(slots=True)
class WeeklyLearningSummary:
    week_start: datetime
    week_end: datetime
    passive_action_counts: dict[str, int] = field(default_factory=dict)
    aggressive_action_counts: dict[str, int] = field(default_factory=dict)
    candidates_evaluated: int = 0
    hit_rate_pct: float | None = None     # % of WATCH+ that moved +ve over 7d
    hit_rate_n: int = 0
    score_mean_this_week: float | None = None
    score_mean_prior_week: float | None = None
    top_decisions: list[dict[str, Any]] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)


def _fwd_return_for_symbol(
    parquet_df, symbol: str, run_at: datetime, days: int = 7,
) -> float | None:
    """Look up close on run_at and close on (run_at + days), return pct change.

    Failures (no data, gap) -> None. Caller treats None as "exclude from
    hit-rate".
    """
    try:
        sub = parquet_df[parquet_df.symbol == symbol].copy()
        if sub.empty:
            return None
        sub["date"] = sub["date"].dt.tz_localize(None) if hasattr(sub["date"].dtype, "tz") and sub["date"].dt.tz is not None else sub["date"]
        sub = sub.sort_values("date")
        run_naive = run_at.replace(tzinfo=None) if run_at.tzinfo else run_at
        # find first row at or after run_at
        on_or_after = sub[sub["date"] >= run_naive]
        if on_or_after.empty:
            return None
        start_close = float(on_or_after.iloc[0]["close"])
        end_target = run_naive + timedelta(days=days)
        end_after = sub[sub["date"] >= end_target]
        if end_after.empty:
            return None
        end_close = float(end_after.iloc[0]["close"])
        if start_close <= 0:
            return None
        return end_close / start_close - 1.0
    except Exception as exc:
        logger.debug("fwd_return failed for %s: %s", symbol, exc)
        return None


def _try_load_parquet():
    parquet = REPO_ROOT / "data" / "historical" / "prices_daily.parquet"
    if not parquet.exists():
        return None
    try:
        import pandas as pd
        df = pd.read_parquet(parquet)
        df["date"] = pd.to_datetime(df["date"])
        return df
    except Exception as exc:
        logger.warning("parquet load failed: %s", exc)
        return None


def build_weekly_summary(
    *, engine, weeks_back: int = 1, now: datetime | None = None,
) -> WeeklyLearningSummary:
    """Aggregate the past `weeks_back` week(s) of decisions and back-evaluate."""
    from sqlalchemy.orm import Session

    from ..models import (
        AggressiveDecision as AggressiveDecisionRow,
    )
    from ..models import (
        CandidateRecord,
    )
    from ..models import (
        PassiveDecision as PassiveDecisionRow,
    )

    now = now or datetime.now(timezone.utc)
    week_end = now
    week_start = now - timedelta(days=7 * max(1, weeks_back))
    prior_week_start = week_start - timedelta(days=7)

    summary = WeeklyLearningSummary(week_start=week_start, week_end=week_end)

    with Session(engine) as s:
        passive_rows = s.query(PassiveDecisionRow).filter(
            PassiveDecisionRow.run_at >= week_start,
            PassiveDecisionRow.run_at <= week_end,
        ).all()
        aggressive_rows = s.query(AggressiveDecisionRow).filter(
            AggressiveDecisionRow.run_at >= week_start,
            AggressiveDecisionRow.run_at <= week_end,
        ).all()
        # Candidate score history for distribution shift.
        cand_this = s.query(CandidateRecord).filter(
            CandidateRecord.run_at >= week_start,
            CandidateRecord.run_at <= week_end,
        ).all()
        cand_prior = s.query(CandidateRecord).filter(
            CandidateRecord.run_at >= prior_week_start,
            CandidateRecord.run_at < week_start,
        ).all()

    summary.passive_action_counts = dict(
        Counter(r.action for r in passive_rows)
    )
    summary.aggressive_action_counts = dict(
        Counter(r.action for r in aggressive_rows)
    )
    summary.candidates_evaluated = len(cand_this)

    if cand_this:
        scores = [float(c.score or 0.0) for c in cand_this]
        summary.score_mean_this_week = sum(scores) / len(scores)
    if cand_prior:
        scores = [float(c.score or 0.0) for c in cand_prior]
        summary.score_mean_prior_week = sum(scores) / len(scores)

    # Hit-rate back-evaluation. Use CandidateRecord rows from
    # prior_week_start..week_start (i.e. ~7-14 days ago) and look up the
    # forward 7d return from parquet.
    parquet = _try_load_parquet()
    if parquet is not None and cand_prior:
        watch_plus = [c for c in cand_prior if c.action in ("STRONG", "WATCH")]
        moves: list[float] = []
        per_decision_moves: list[tuple[Any, float]] = []
        for c in watch_plus:
            ret = _fwd_return_for_symbol(parquet, c.symbol, c.run_at, days=7)
            if ret is None:
                continue
            moves.append(ret)
            per_decision_moves.append((c, ret))
        if moves:
            summary.hit_rate_pct = (
                sum(1 for m in moves if m > 0) / len(moves) * 100.0
            )
            summary.hit_rate_n = len(moves)
            # Top 5 by realised move.
            per_decision_moves.sort(key=lambda t: -t[1])
            summary.top_decisions = [
                {
                    "symbol": c.symbol,
                    "action": c.action,
                    "score": float(c.score or 0.0),
                    "run_at": c.run_at.isoformat() if c.run_at else None,
                    "fwd_7d_pct": round(ret * 100, 2),
                }
                for c, ret in per_decision_moves[:5]
            ]
    elif parquet is None:
        summary.blockers.append("parquet historical data missing — hit-rate skipped")

    return summary


def render_markdown(summary: WeeklyLearningSummary) -> str:
    lines: list[str] = []
    lines.append(
        f"# Crypto Learning Summary  "
        f"{summary.week_start.date().isoformat()} -> "
        f"{summary.week_end.date().isoformat()}"
    )
    lines.append("")
    lines.append(f"_Generated {datetime.now(timezone.utc).isoformat(timespec='minutes')}_")
    lines.append("")
    lines.append("## Decision counts")
    lines.append("")
    if summary.passive_action_counts:
        lines.append("**Passive**")
        for k, v in sorted(summary.passive_action_counts.items()):
            lines.append(f"- {k}: {v}")
    else:
        lines.append("- no passive decisions in window")
    lines.append("")
    if summary.aggressive_action_counts:
        lines.append("**Aggressive**")
        for k, v in sorted(summary.aggressive_action_counts.items()):
            lines.append(f"- {k}: {v}")
    else:
        lines.append("- no aggressive decisions in window")

    lines.append("")
    lines.append("## Hit rate (back-eval from prior week)")
    lines.append("")
    if summary.hit_rate_pct is None:
        lines.append("- insufficient history to compute hit rate")
    else:
        lines.append(
            f"- WATCH+ symbols 7-14d ago that moved positively over the next 7d: "
            f"**{summary.hit_rate_pct:.1f}%** (n={summary.hit_rate_n})"
        )
    lines.append("")
    lines.append("## Score distribution shift")
    lines.append("")
    if summary.score_mean_this_week is not None:
        lines.append(f"- mean score this week: {summary.score_mean_this_week:+.3f}")
    if summary.score_mean_prior_week is not None:
        lines.append(f"- mean score prior week: {summary.score_mean_prior_week:+.3f}")
    if summary.top_decisions:
        lines.append("")
        lines.append("## Top realised moves (prior-week candidates)")
        lines.append("")
        lines.append("| Symbol | Action | Score | 7d move |")
        lines.append("|---|---|---|---|")
        for t in summary.top_decisions:
            lines.append(
                f"| {t['symbol']} | {t['action']} | {t['score']:+.2f} | "
                f"{t['fwd_7d_pct']:+.2f}% |"
            )
    if summary.blockers:
        lines.append("")
        lines.append("## Blockers")
        for b in summary.blockers:
            lines.append(f"- {b}")
    lines.append("")
    return "\n".join(lines)


def render_telegram(summary: WeeklyLearningSummary) -> str:
    def _esc(s: str) -> str:
        return html.escape(str(s), quote=False)

    lines: list[str] = []
    lines.append(
        f"🧠 <b>CRYPTO LEARNING SUMMARY</b>  "
        f"{_esc(summary.week_start.date().isoformat())} -> "
        f"{_esc(summary.week_end.date().isoformat())}"
    )

    if summary.passive_action_counts:
        chunks = [f"{k}={v}" for k, v in sorted(summary.passive_action_counts.items())]
        lines.append(f"\n<b>Passive</b>: " + _esc(" · ".join(chunks)))
    if summary.aggressive_action_counts:
        chunks = [f"{k}={v}" for k, v in sorted(summary.aggressive_action_counts.items())]
        lines.append(f"<b>Aggressive</b>: " + _esc(" · ".join(chunks)))

    if summary.hit_rate_pct is not None:
        lines.append(
            f"\n<b>Hit rate</b> (WATCH+ -> +ve 7d): "
            f"{summary.hit_rate_pct:.1f}% (n={summary.hit_rate_n})"
        )
    else:
        lines.append("\n<b>Hit rate</b>: insufficient history")

    if summary.score_mean_this_week is not None or summary.score_mean_prior_week is not None:
        s_this = summary.score_mean_this_week
        s_prev = summary.score_mean_prior_week
        s_this_str = f"{s_this:+.3f}" if s_this is not None else "n/a"
        s_prev_str = f"{s_prev:+.3f}" if s_prev is not None else "n/a"
        lines.append(
            f"<b>Mean score</b>: this week {s_this_str} · prior week {s_prev_str}"
        )

    if summary.top_decisions:
        lines.append("\n<b>Top realised moves</b>:")
        for t in summary.top_decisions[:5]:
            lines.append(
                f"  · {_esc(t['symbol'])} {_esc(t['action'])} "
                f"score={t['score']:+.2f}  fwd7d={t['fwd_7d_pct']:+.2f}%"
            )

    if summary.blockers:
        lines.append("\n<i>Blockers:</i>")
        for b in summary.blockers[:5]:
            lines.append(f"  · {_esc(b)}")

    return "\n".join(lines)


def write_markdown_report(
    summary: WeeklyLearningSummary, *, reports_dir: Path | str | None = None,
) -> Path:
    rd = Path(reports_dir) if reports_dir else REPO_ROOT / "reports"
    rd.mkdir(parents=True, exist_ok=True)
    date = summary.week_end.date().isoformat()
    path = rd / f"learning_summary_{date}.md"
    path.write_text(render_markdown(summary))
    return path


def persist_summary(engine, summary: WeeklyLearningSummary) -> None:
    if engine is None:
        return
    from sqlalchemy.orm import Session

    from ..models import LearningSummaryRecord

    payload = {
        "passive_action_counts": summary.passive_action_counts,
        "aggressive_action_counts": summary.aggressive_action_counts,
        "candidates_evaluated": summary.candidates_evaluated,
        "hit_rate_pct": summary.hit_rate_pct,
        "hit_rate_n": summary.hit_rate_n,
        "score_mean_this_week": summary.score_mean_this_week,
        "score_mean_prior_week": summary.score_mean_prior_week,
        "top_decisions": summary.top_decisions,
        "blockers": summary.blockers,
    }
    with Session(engine) as s:
        s.add(LearningSummaryRecord(
            run_at=datetime.now(timezone.utc),
            week_ending=summary.week_end,
            payload=payload,
        ))
        s.commit()


def send_learning_telegram(summary: WeeklyLearningSummary, *, http=None) -> bool:
    text = render_telegram(summary)
    if not text.strip():
        return False
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    enabled_raw = os.environ.get("TELEGRAM_ENABLED", "true").lower()
    if enabled_raw in ("false", "0", "no"):
        return False
    if not (token and chat_id):
        return False
    try:
        if http is None:
            import httpx
            http = httpx
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        resp = http.post(
            url,
            json={
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
            timeout=15.0,
        )
        resp.raise_for_status()
        return True
    except Exception as exc:
        logger.warning("learning-summary telegram failed: %s", exc)
        return False
