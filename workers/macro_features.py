"""ARGOS macro feature block builder."""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal

import asyncpg

# ``cpi_surprise`` is intentionally unset until a consensus-expectations feed exists.
OPTIONAL_DERIVED_FEATURE_KEYS = frozenset({"cpi_surprise"})

DERIVED_FEATURE_KEYS = [
    "fed_funds_change_30d",
    "yield_10y_change_30d",
    "yield_2y_change_30d",
    "ten_year_yield_change_30d",
    "spread_2s10s_change_30d",
    "cpi_yoy_pct",
    "gdp_qoq_pct",
    "vix_change_5d",
    "vix_pct_rank_1y",
    "hy_oas_change_30d",
    "sp500_change_5d_pct",
    "sp500_change_30d_pct",
    "nasdaq_change_5d_pct",
    "nasdaq_change_30d_pct",
    "dxy_change_5d",
    "dxy_change_30d",
]


def _json_scalar(value: object) -> object:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def build_macro_feature_block_from_row(
    row: dict[str, object] | asyncpg.Record | None,
) -> dict[str, object]:
    """Build the macro block for ARGOS, preserving nulls and listing data gaps."""
    if row is None:
        return {"data_gaps": ["macro_context"]}

    source = dict(row)
    block = {
        "as_of_date": _json_scalar(source.get("as_of_date")),
        "fed_funds_rate": _json_scalar(source.get("fed_funds_rate")),
        "yield_2y": _json_scalar(source.get("yield_2y")),
        "yield_10y": _json_scalar(source.get("yield_10y")),
        "spread_2s10s": _json_scalar(source.get("spread_2s10s")),
        "fed_funds_change_30d": _json_scalar(source.get("fed_funds_change_30d")),
        "yield_10y_change_30d": _json_scalar(source.get("yield_10y_change_30d")),
        "yield_2y_change_30d": _json_scalar(source.get("yield_2y_change_30d")),
        "ten_year_yield_change_30d": _json_scalar(source.get("yield_10y_change_30d")),
        "spread_2s10s_change_30d": _json_scalar(source.get("spread_2s10s_change_30d")),
        "cpi": _json_scalar(source.get("cpi")),
        "cpi_yoy_pct": _json_scalar(source.get("cpi_yoy_pct")),
        "cpi_surprise": _json_scalar(source.get("cpi_surprise")),
        "gdp": _json_scalar(source.get("gdp")),
        "gdp_qoq_pct": _json_scalar(source.get("gdp_qoq_pct")),
        "vix": _json_scalar(source.get("vix")),
        "vix_change_5d": _json_scalar(source.get("vix_change_5d")),
        "vix_pct_rank_1y": _json_scalar(source.get("vix_pct_rank_1y")),
        "hy_oas_bps": _json_scalar(source.get("hy_oas_bps")),
        "hy_oas_change_30d": _json_scalar(source.get("hy_oas_change_30d")),
        "sp500_level": _json_scalar(source.get("sp500_level")),
        "sp500_change_5d_pct": _json_scalar(source.get("sp500_change_5d_pct")),
        "sp500_change_30d_pct": _json_scalar(source.get("sp500_change_30d_pct")),
        "nasdaq_level": _json_scalar(source.get("nasdaq_level")),
        "nasdaq_change_5d_pct": _json_scalar(source.get("nasdaq_change_5d_pct")),
        "nasdaq_change_30d_pct": _json_scalar(source.get("nasdaq_change_30d_pct")),
        "dxy": _json_scalar(source.get("dxy")),
        "dxy_change_5d": _json_scalar(source.get("dxy_change_5d")),
        "dxy_change_30d": _json_scalar(source.get("dxy_change_30d")),
        "rate_environment": source.get("rate_environment"),
        "yield_curve": source.get("yield_curve"),
        "credit_environment": source.get("credit_environment"),
        "volatility_regime": source.get("volatility_regime"),
        "dollar_regime": source.get("dollar_regime"),
        "style_tilts": _json_scalar(source.get("style_tilts") or {}),
        "data_gaps": [],
    }
    block["data_gaps"] = [
        key
        for key in DERIVED_FEATURE_KEYS
        if key not in OPTIONAL_DERIVED_FEATURE_KEYS and block.get(key) is None
    ]
    return block


async def fetch_argos_macro_feature_block(
    conn: asyncpg.Connection,
    *,
    trade_date: date,
    worker_name: str = "ArgosContextWorker",
) -> dict[str, object]:
    """Fetch the latest canonical macro row for ARGOS and alert on missing context."""
    last_trading_day = await conn.fetchval(
        """
        SELECT calendar_date
          FROM theeyebeta.trading_calendar
         WHERE calendar_date <= $1
           AND is_trading_day
         ORDER BY calendar_date DESC
         LIMIT 1
        """,
        trade_date,
    )
    expected_date = last_trading_day or trade_date
    row = await conn.fetchrow(
        """
        SELECT *
          FROM theeyebeta.macro_regime_snapshots
         WHERE as_of_date = $1
         ORDER BY as_of_date DESC
         LIMIT 1
        """,
        expected_date,
    )
    if row is None:
        await conn.execute(
            """
            INSERT INTO theeyebeta.audit_alerts
                (alert_type, severity, trade_date, worker_name, title, message, metadata)
            VALUES (
                'DATA_GAP',
                'WARN',
                $1,
                $2,
                'Macro context missing',
                $3,
                $4::jsonb
            )
            """,
            expected_date,
            worker_name,
            f"No macro snapshot row exists for last trading day {expected_date}.",
            json.dumps({"data_gaps": ["macro_context"]}),
        )
        return {"data_gaps": ["macro_context"]}
    return build_macro_feature_block_from_row(row)
