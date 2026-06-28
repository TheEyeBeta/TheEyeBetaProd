"""Load chart-ready price/indicator bundles from theeyebeta schema."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Literal

from tb.lib.db import sync_connect

RangeLiteral = Literal["1y", "2y", "5y"]


@dataclass
class CorporateActionEvent:
    action_date: str
    action_type: str
    split_ratio: float | None = None
    dividend_amount: float | None = None
    notes: str | None = None


@dataclass
class ChartBundle:
    instrument_id: int
    ticker: str
    dates: list[str]
    prices: dict[str, list[float | None]]
    volume: list[int | None]
    indicators: dict[str, list[float | bool | None]]
    as_of_date: date
    corporate_actions: list[CorporateActionEvent] | None = None


def _range_start(end: date, range_key: RangeLiteral) -> date:
    days = {"1y": 365, "2y": 730, "5y": 1825}[range_key]
    return end - timedelta(days=days)


def load_chart_bundle(ticker: str, range_key: RangeLiteral = "2y") -> ChartBundle:
    """Load aligned price + indicator series for plotting."""
    symbol = ticker.upper()
    end_date = date.today()
    start_date = _range_start(end_date, range_key)

    with sync_connect() as conn:
        inst = conn.execute(
            """
            SELECT id, symbol FROM theeyebeta.instruments
             WHERE UPPER(symbol) = %s LIMIT 1
            """,
            (symbol,),
        ).fetchone()
        if not inst:
            raise ValueError(f"Ticker {symbol} not found")

        iid = int(inst["id"])
        price_rows = conn.execute(
            """
            WITH ranked_prices AS (
                SELECT ts::date AS d, open, high, low, close, adj_close, volume,
                       ROW_NUMBER() OVER (
                           PARTITION BY ts::date
                           ORDER BY
                               CASE source
                                   WHEN 'massive' THEN 100
                                   WHEN 'yfinance_backfill_prices' THEN 90
                                   WHEN 'yfinance_gap_fix' THEN 90
                                   WHEN 'yfinance' THEN 80
                                   WHEN 'finnhub' THEN 70
                                   WHEN 'public_mirror_backfill' THEN 60
                                   WHEN 'public_mirror_active_universe' THEN 50
                                   WHEN 'tick_rollup' THEN 40
                                   WHEN 'csv' THEN 10
                                   ELSE 0
                               END DESC,
                               ts DESC,
                               ingested_at DESC
                       ) AS rn
                  FROM theeyebeta.prices_daily
                 WHERE instrument_id = %s
                   AND ts::date >= %s AND ts::date <= %s
            )
            SELECT d, open, high, low, close, adj_close, volume
              FROM ranked_prices
             WHERE rn = 1
             ORDER BY d
            """,
            (iid, start_date, end_date),
        ).fetchall()

        if not price_rows:
            raise ValueError(f"No price data for {symbol} in {range_key} range")

        ind_rows = conn.execute(
            """
            SELECT date, sma_10, sma_50, sma_200, ema_10, ema_50, ema_200,
                   ema_12, ema_26, rsi_14, macd, macd_signal, macd_hist,
                   golden_cross_sma, death_cross_sma
              FROM theeyebeta.ind_technical_daily
             WHERE instrument_id = %s
               AND date >= %s AND date <= %s
             ORDER BY date
            """,
            (iid, start_date, end_date),
        ).fetchall()

        ca_rows = conn.execute(
            """
            SELECT ex_date, action_type, ratio_num, ratio_den, cash_amount
              FROM theeyebeta.corporate_actions
             WHERE instrument_id = %s
               AND ex_date >= %s AND ex_date <= %s
             ORDER BY ex_date
            """,
            (iid, start_date, end_date),
        ).fetchall()

    prices_by_date = {r["d"]: r for r in price_rows}
    ind_by_date = {r["date"]: r for r in ind_rows}
    all_dates = sorted(set(prices_by_date) | set(ind_by_date))

    prices_dict: dict[str, list[float | None]] = {
        "close": [],
        "adj_close": [],
        "open": [],
        "high": [],
        "low": [],
    }
    volume_list: list[int | None] = []
    indicators_dict: dict[str, list[float | bool | None]] = {
        "sma_10": [],
        "sma_50": [],
        "sma_200": [],
        "ema_10": [],
        "ema_50": [],
        "ema_200": [],
        "ema_12": [],
        "ema_26": [],
        "rsi_14": [],
        "macd": [],
        "macd_signal": [],
        "macd_hist": [],
        "golden_cross_sma": [],
        "death_cross_sma": [],
    }

    for d in all_dates:
        p = prices_by_date.get(d)
        if p:
            prices_dict["close"].append(float(p["close"]))
            prices_dict["adj_close"].append(
                float(p["adj_close"]) if p["adj_close"] is not None else None
            )
            prices_dict["open"].append(float(p["open"]) if p["open"] is not None else None)
            prices_dict["high"].append(float(p["high"]) if p["high"] is not None else None)
            prices_dict["low"].append(float(p["low"]) if p["low"] is not None else None)
            volume_list.append(int(p["volume"]) if p["volume"] is not None else None)
        else:
            for key in prices_dict:
                prices_dict[key].append(None)
            volume_list.append(None)

        ind = ind_by_date.get(d)
        bool_keys = {"golden_cross_sma", "death_cross_sma"}
        for key in indicators_dict:
            if ind and ind.get(key) is not None:
                val = ind[key]
                if key in bool_keys:
                    indicators_dict[key].append(bool(val))
                else:
                    indicators_dict[key].append(float(val))
            else:
                indicators_dict[key].append(None)

    corp_actions = []
    for row in ca_rows:
        split_ratio = None
        if row["action_type"] == "split" and row["ratio_num"] and row["ratio_den"]:
            split_ratio = float(row["ratio_num"]) / float(row["ratio_den"])
        corp_actions.append(
            CorporateActionEvent(
                action_date=row["ex_date"].isoformat(),
                action_type=row["action_type"].upper(),
                split_ratio=split_ratio,
                dividend_amount=(
                    float(row["cash_amount"]) if row["cash_amount"] is not None else None
                ),
            )
        )

    return ChartBundle(
        instrument_id=iid,
        ticker=symbol,
        dates=[d.isoformat() for d in all_dates],
        prices=prices_dict,
        volume=volume_list,
        indicators=indicators_dict,
        as_of_date=all_dates[-1],
        corporate_actions=corp_actions,
    )
