"""Tests for the order supervisor."""

from __future__ import annotations

from datetime import UTC, datetime

from crypto_research_watchlist.autotrader.order_supervisor import (
    format_supervisor_message,
    reconcile,
)


class _FakeBroker:
    def __init__(self, cash: float, positions: list):
        self._cash = cash
        self._positions = positions

    def get_cash(self) -> float:
        return self._cash

    def get_positions(self):
        return self._positions


class _FakePosition:
    def __init__(self, symbol: str, quantity: float, avg_price: float):
        self.symbol = symbol
        self.quantity = quantity
        self.avg_price = avg_price


def test_clean_state_yields_no_warnings(engine):
    broker = _FakeBroker(cash=5000.0, positions=[])
    report = reconcile(engine=engine, broker=broker)
    assert report.warnings == []
    assert report.mismatches == 0
    assert report.cash_usd == 5000.0
    assert report.positions_count == 0


def test_orphan_position_flagged(engine):
    broker = _FakeBroker(
        cash=4900.0,
        positions=[_FakePosition("BTC-USD", quantity=0.001, avg_price=100000.0)],
    )
    report = reconcile(engine=engine, broker=broker)
    assert report.mismatches == 1
    assert any("BTC-USD" in w for w in report.warnings)


def test_non_shadow_buy_without_position_flagged(engine):
    from sqlalchemy.orm import Session

    from crypto_research_watchlist.models import (
        PassiveDecision as PassiveDecisionRow,
    )

    with Session(engine) as s:
        s.add(PassiveDecisionRow(
            run_at=datetime.now(UTC),
            symbol="ETH-USD", action="AUTO_BUY_FIRST_TRANCHE",
            accumulation_score=0.6, tranche_usd=100.0,
            reasons={"reasons": ["test"]}, shadow_mode=0,
        ))
        s.commit()

    broker = _FakeBroker(cash=5000.0, positions=[])
    report = reconcile(engine=engine, broker=broker)
    # ETH decision exists but no position -> mismatch.
    assert report.mismatches >= 1
    assert any("ETH-USD" in w for w in report.warnings)


def test_format_message_empty_when_clean():
    from crypto_research_watchlist.autotrader.order_supervisor import (
        SupervisorReport,
    )
    msg = format_supervisor_message(SupervisorReport())
    assert msg == ""


def test_format_message_includes_warnings():
    from crypto_research_watchlist.autotrader.order_supervisor import (
        SupervisorReport,
    )
    msg = format_supervisor_message(SupervisorReport(
        mismatches=1, warnings=["BTC-USD: stuck"],
    ))
    assert "CRYPTO SUPERVISOR" in msg
    assert "BTC-USD" in msg
