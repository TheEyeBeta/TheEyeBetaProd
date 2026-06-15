"""US equity intraday bars via alpaca-py Market Data API."""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

import structlog

from data_ingestion.adapters.base import _US_EXCHANGES, load_active_instruments, make_http_client
from zinc_schemas.ingestion import IntradayBarRecord, Record

log = structlog.get_logger()

def _bar_specs() -> tuple[tuple[int, object], ...]:
    from alpaca.data.timeframe import TimeFrame, TimeFrameUnit  # noqa: PLC0415

    return (
        (60, TimeFrame(1, TimeFrameUnit.Minute)),
        (300, TimeFrame(5, TimeFrameUnit.Minute)),
    )


def _bar_timestamp_to_datetime(ts: datetime | str) -> datetime:
    if isinstance(ts, datetime):
        return ts if ts.tzinfo else ts.replace(tzinfo=UTC)
    return datetime.fromisoformat(str(ts)).astimezone(UTC)


class AlpacaDataAdapter:
    """1-minute and 5-minute US equity bars from Alpaca Market Data."""

    name = "alpaca_data"

    def __init__(self, instruments: list[dict[str, Any]] | None = None) -> None:
        self._instruments = instruments

    def _client(self) -> object:
        from alpaca.data.historical import StockHistoricalDataClient  # noqa: PLC0415

        key = os.environ.get("APCA_API_KEY_ID") or os.environ.get("ALPACA_API_KEY", "")
        secret = os.environ.get("APCA_API_SECRET_KEY") or os.environ.get(
            "ALPACA_API_SECRET",
            "",
        )
        if not key or not secret:
            raise OSError(
                "APCA_API_KEY_ID and APCA_API_SECRET_KEY (or ALPACA_API_KEY/SECRET) must be set"
            )
        return StockHistoricalDataClient(key, secret)

    async def fetch(self, target_date: date) -> AsyncIterator[Record]:
        """Yield 1m and 5m intraday bars for active US listings."""
        instruments = self._instruments
        if instruments is None:
            all_inst = await load_active_instruments()
            instruments = [i for i in all_inst if str(i["exchange_code"]) in _US_EXCHANGES]

        if not instruments:
            log.info("alpaca_no_instruments", date=str(target_date))
            return

        symbols = [str(i["symbol"]) for i in instruments]
        symbol_to_id = {str(i["symbol"]): int(i["instrument_id"]) for i in instruments}
        start_dt = datetime.combine(target_date, time.min, tzinfo=UTC)
        end_dt = start_dt + timedelta(days=1)
        loop = asyncio.get_running_loop()
        client = self._client()

        from alpaca.data.requests import StockBarsRequest  # noqa: PLC0415

        async with make_http_client():
            for bar_seconds, timeframe in _bar_specs():
                request = StockBarsRequest(
                    symbol_or_symbols=symbols,
                    timeframe=timeframe,
                    start=start_dt,
                    end=end_dt,
                )
                try:
                    bars_map = await loop.run_in_executor(None, client.get_stock_bars, request)
                except Exception as exc:  # noqa: BLE001
                    log.warning(
                        "alpaca_fetch_failed",
                        bar_seconds=bar_seconds,
                        error=str(exc),
                    )
                    continue

                for symbol, bars in bars_map.data.items():
                    instrument_id = symbol_to_id.get(str(symbol))
                    if instrument_id is None:
                        continue
                    for bar in bars:
                        observed = _bar_timestamp_to_datetime(bar.timestamp)
                        if observed.date() != target_date:
                            continue
                        yield IntradayBarRecord(
                            source="alpaca_data",
                            observed_at=observed,
                            instrument_id=instrument_id,
                            symbol=str(symbol),
                            bar_seconds=bar_seconds,
                            open=float(bar.open),
                            high=float(bar.high),
                            low=float(bar.low),
                            close=float(bar.close),
                            volume=int(bar.volume),
                        )
