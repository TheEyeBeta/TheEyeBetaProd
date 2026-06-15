"""Shanghai/Shenzhen daily prices via yfinance (.SS/.SZ) with ADR fallback."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import date
from typing import Any

import structlog
import yaml

from data_ingestion.adapters.base import (
    _CN_EXCHANGES,
    _CONFIG_DIR,
    load_active_instruments,
    make_http_client,
)
from data_ingestion.adapters.yfinance import _fetch_sync, make_ticker
from zinc_schemas.ingestion import PriceDailyRecord, Record

log = structlog.get_logger()

_SEMAPHORE_LIMIT = 3


def _load_adr_fallbacks() -> dict[tuple[str, str], str]:
    path = _CONFIG_DIR / "cn_adr_fallback.yaml"
    if not path.exists():
        return {}
    config = yaml.safe_load(path.read_text(encoding="utf-8"))
    mapping: dict[tuple[str, str], str] = {}
    for entry in config.get("fallbacks", []):
        key = (str(entry["symbol"]), str(entry["exchange_code"]))
        mapping[key] = str(entry["adr_ticker"])
    return mapping


class CnProxyAdapter:
    """China A-share daily bars with optional US ADR fallback tickers."""

    name = "cn_proxy"

    def __init__(
        self,
        instruments: list[dict[str, Any]] | None = None,
        *,
        adr_fallbacks: dict[tuple[str, str], str] | None = None,
    ) -> None:
        self._instruments = instruments
        self._adr_fallbacks = adr_fallbacks if adr_fallbacks is not None else _load_adr_fallbacks()

    async def fetch(self, target_date: date) -> AsyncIterator[Record]:
        """Yield daily CN (and fallback ADR) price records."""
        instruments = self._instruments
        if instruments is None:
            all_inst = await load_active_instruments()
            instruments = [i for i in all_inst if str(i["exchange_code"]) in _CN_EXCHANGES]

        sem = asyncio.Semaphore(_SEMAPHORE_LIMIT)
        loop = asyncio.get_running_loop()

        async def _one(inst: dict[str, Any]) -> list[PriceDailyRecord]:
            symbol = str(inst["symbol"])
            exchange = str(inst["exchange_code"])
            instrument_id = int(inst["instrument_id"])
            tickers = [make_ticker(symbol, exchange)]
            adr = self._adr_fallbacks.get((symbol, exchange))
            if adr:
                tickers.append(adr)

            async with sem, make_http_client():
                for ticker_sym in tickers:
                    try:
                        records = await loop.run_in_executor(
                            None,
                            _fetch_sync,
                            ticker_sym,
                            instrument_id,
                            symbol,
                            exchange,
                            target_date,
                        )
                    except Exception as exc:  # noqa: BLE001
                        log.warning(
                            "cn_proxy_fetch_failed",
                            ticker=ticker_sym,
                            error=str(exc),
                        )
                        continue
                    if records:
                        if ticker_sym != tickers[0]:
                            log.info(
                                "cn_proxy_adr_fallback_used",
                                symbol=symbol,
                                adr_ticker=ticker_sym,
                            )
                        return [r.model_copy(update={"source": "cn_proxy"}) for r in records]
            return []

        results = await asyncio.gather(*[_one(inst) for inst in instruments])
        for batch in results:
            for record in batch:
                yield record
