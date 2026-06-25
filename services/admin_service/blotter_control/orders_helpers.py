"""Shared order row mapping for blotter APIs."""

from __future__ import annotations

from decimal import Decimal

import asyncpg

from zinc_schemas.admin_dto import InstrumentSummary, OrderSummary


def row_to_summary(row: asyncpg.Record) -> OrderSummary:
    return OrderSummary(
        id=row["id"],
        client_order_id=row["client_order_id"],
        portfolio_id=row["portfolio_id"],
        instrument=InstrumentSummary(
            id=int(row["instrument_id"]),
            symbol=row["instrument_symbol"],
            exchange_code=row["exchange_code"],
        ),
        side=row["side"],
        order_type=row["order_type"],
        qty=Decimal(str(row["qty"])),
        limit_price=Decimal(str(row["limit_price"])) if row["limit_price"] is not None else None,
        status=row["status"],
        created_at=row["created_at"],
    )
