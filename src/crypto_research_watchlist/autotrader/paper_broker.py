"""Paper broker.

Simulates fills against a quote source (last close from the price panel
or an injected QuoteFn). Persists every order, position, and the cash
balance to SQLAlchemy via the same models the real autotrader uses.

Idempotency: orders are keyed by ``client_order_key``. Re-submitting the
same key returns the existing order rather than creating a new one or
double-counting cash.

Slippage and transaction cost are taken from config.backtesting (10 bps txn,
8 bps slippage per side) so paper performance is comparable to the
backtest baseline.

The broker DOES NOT touch any exchange. There are no API keys.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from ..db import session_factory, session_scope
from ..models import PaperCash, PaperOrder, PaperPosition

logger = logging.getLogger(__name__)


QuoteFn = Callable[[str], float | None]


class PaperBrokerError(Exception):
    pass


@dataclass(slots=True)
class FillResult:
    client_order_key: str
    symbol: str
    side: str
    quantity: float
    fill_price: float
    status: str  # FILLED / REJECTED / DUPLICATE


class PaperBroker:
    """In-process paper broker. Persists state to the same DB the pipeline uses."""

    def __init__(
        self,
        engine: Engine,
        *,
        quote_fn: QuoteFn,
        starting_cash: float = 5000.0,
        txn_cost_bps: float = 10.0,
        slippage_bps: float = 8.0,
    ) -> None:
        self._engine = engine
        self._SessionLocal = session_factory(engine)
        self._quote = quote_fn
        self._starting_cash = starting_cash
        self._txn_cost_bps = txn_cost_bps
        self._slippage_bps = slippage_bps
        self._ensure_cash_row()

    # ---- Internals ----
    def _ensure_cash_row(self) -> None:
        with session_scope(self._SessionLocal) as session:
            row = session.get(PaperCash, 1)
            if row is None:
                session.add(PaperCash(id=1, cash_usd=self._starting_cash))

    def _adjust_cash(self, session: Session, delta: float) -> None:
        row = session.get(PaperCash, 1)
        if row is None:
            row = PaperCash(id=1, cash_usd=self._starting_cash)
            session.add(row)
        row.cash_usd = float(row.cash_usd + delta)

    def _slip_buy(self, px: float) -> float:
        return px * (1 + self._slippage_bps / 10_000)

    def _slip_sell(self, px: float) -> float:
        return px * (1 - self._slippage_bps / 10_000)

    def _txn_cost(self, notional: float) -> float:
        return abs(notional) * (self._txn_cost_bps / 10_000)

    # ---- Public API ----
    def get_cash(self) -> float:
        with session_scope(self._SessionLocal) as session:
            row = session.get(PaperCash, 1)
            return float(row.cash_usd) if row else 0.0

    def get_position(self, symbol: str) -> PaperPosition | None:
        with session_scope(self._SessionLocal) as session:
            return session.get(PaperPosition, symbol)

    def get_positions(self) -> list[PaperPosition]:
        with session_scope(self._SessionLocal) as session:
            return list(session.scalars(select(PaperPosition)).all())

    def place_market_order(
        self,
        *,
        symbol: str,
        side: str,
        quantity: float,
        client_order_key: str,
    ) -> FillResult:
        side = side.upper()
        if side not in {"BUY", "SELL"}:
            raise PaperBrokerError(f"side must be BUY or SELL, got {side!r}")
        if quantity <= 0:
            raise PaperBrokerError(f"quantity must be positive, got {quantity}")

        with session_scope(self._SessionLocal) as session:
            existing = session.scalars(
                select(PaperOrder).where(PaperOrder.client_order_key == client_order_key)
            ).one_or_none()
            if existing is not None:
                return FillResult(
                    client_order_key=client_order_key,
                    symbol=existing.symbol,
                    side=existing.side,
                    quantity=existing.quantity,
                    fill_price=existing.fill_price or 0.0,
                    status="DUPLICATE",
                )

            quote = self._quote(symbol)
            if quote is None or quote <= 0:
                # Persist rejection so an audit can find it.
                session.add(PaperOrder(
                    client_order_key=client_order_key,
                    symbol=symbol,
                    side=side,
                    order_type="MARKET",
                    quantity=quantity,
                    fill_price=None,
                    status="REJECTED",
                ))
                return FillResult(client_order_key, symbol, side, quantity, 0.0, "REJECTED")

            fill_px = self._slip_buy(quote) if side == "BUY" else self._slip_sell(quote)
            notional = fill_px * quantity
            txn = self._txn_cost(notional)

            cash_row = session.get(PaperCash, 1)
            cash = float(cash_row.cash_usd) if cash_row else 0.0
            if side == "BUY":
                if cash < notional + txn:
                    session.add(PaperOrder(
                        client_order_key=client_order_key,
                        symbol=symbol,
                        side=side,
                        order_type="MARKET",
                        quantity=quantity,
                        fill_price=None,
                        status="REJECTED",
                    ))
                    return FillResult(client_order_key, symbol, side, quantity, 0.0, "REJECTED")
                self._adjust_cash(session, -(notional + txn))
            else:  # SELL
                pos = session.get(PaperPosition, symbol)
                held = float(pos.quantity) if pos else 0.0
                if held < quantity:
                    session.add(PaperOrder(
                        client_order_key=client_order_key,
                        symbol=symbol,
                        side=side,
                        order_type="MARKET",
                        quantity=quantity,
                        fill_price=None,
                        status="REJECTED",
                    ))
                    return FillResult(client_order_key, symbol, side, quantity, 0.0, "REJECTED")
                self._adjust_cash(session, +(notional - txn))

            # Update position.
            pos = session.get(PaperPosition, symbol)
            if pos is None:
                pos = PaperPosition(symbol=symbol, quantity=0.0, avg_price=0.0)
                session.add(pos)
            if side == "BUY":
                new_qty = pos.quantity + quantity
                # Cost-basis-weighted avg.
                pos.avg_price = (
                    (pos.avg_price * pos.quantity + fill_px * quantity) / new_qty
                    if new_qty > 0
                    else 0.0
                )
                pos.quantity = new_qty
            else:
                realised = (fill_px - pos.avg_price) * quantity
                pos.realised_pnl = float(pos.realised_pnl + realised)
                pos.quantity = pos.quantity - quantity
                if pos.quantity <= 1e-12:
                    pos.quantity = 0.0
                    pos.avg_price = 0.0

            session.add(PaperOrder(
                client_order_key=client_order_key,
                symbol=symbol,
                side=side,
                order_type="MARKET",
                quantity=quantity,
                fill_price=fill_px,
                status="FILLED",
            ))
            return FillResult(client_order_key, symbol, side, quantity, fill_px, "FILLED")
