"""Paper broker tests: buy/sell, idempotency, slippage, rejection."""

from __future__ import annotations

from crypto_research_watchlist.autotrader.paper_broker import PaperBroker


def _quote_fn(prices):
    def q(symbol):
        return prices.get(symbol)
    return q


def test_buy_then_sell_round_trip(engine):
    prices = {"BTC-USD": 100.0}
    broker = PaperBroker(engine, quote_fn=_quote_fn(prices), starting_cash=10_000)
    fill = broker.place_market_order(
        symbol="BTC-USD", side="BUY", quantity=10, client_order_key="k1",
    )
    assert fill.status == "FILLED"
    assert fill.fill_price > 100.0  # slippage applied

    pos = broker.get_position("BTC-USD")
    assert pos.quantity == 10

    prices["BTC-USD"] = 120.0
    fill2 = broker.place_market_order(
        symbol="BTC-USD", side="SELL", quantity=10, client_order_key="k2",
    )
    assert fill2.status == "FILLED"
    pos = broker.get_position("BTC-USD")
    assert pos.quantity == 0
    assert pos.realised_pnl > 0


def test_idempotency_by_client_order_key(engine):
    prices = {"BTC-USD": 100.0}
    broker = PaperBroker(engine, quote_fn=_quote_fn(prices), starting_cash=10_000)
    f1 = broker.place_market_order(
        symbol="BTC-USD", side="BUY", quantity=1, client_order_key="dup-key",
    )
    f2 = broker.place_market_order(
        symbol="BTC-USD", side="BUY", quantity=1, client_order_key="dup-key",
    )
    assert f1.status == "FILLED"
    assert f2.status == "DUPLICATE"
    pos = broker.get_position("BTC-USD")
    assert pos.quantity == 1


def test_buy_rejected_when_insufficient_cash(engine):
    prices = {"BTC-USD": 100.0}
    broker = PaperBroker(engine, quote_fn=_quote_fn(prices), starting_cash=50)
    f = broker.place_market_order(
        symbol="BTC-USD", side="BUY", quantity=10, client_order_key="too-much",
    )
    assert f.status == "REJECTED"
    pos = broker.get_position("BTC-USD")
    assert pos is None or pos.quantity == 0


def test_sell_rejected_when_no_position(engine):
    prices = {"BTC-USD": 100.0}
    broker = PaperBroker(engine, quote_fn=_quote_fn(prices), starting_cash=10_000)
    f = broker.place_market_order(
        symbol="BTC-USD", side="SELL", quantity=1, client_order_key="naked",
    )
    assert f.status == "REJECTED"


def test_quote_missing_rejects(engine):
    broker = PaperBroker(engine, quote_fn=lambda _s: None, starting_cash=10_000)
    f = broker.place_market_order(
        symbol="BTC-USD", side="BUY", quantity=1, client_order_key="no-quote",
    )
    assert f.status == "REJECTED"
