"""Pydantic models for the theeyebeta market-data snapshot contract.

Schema version history
----------------------
1 (current): initial release — prices, technicals, macro, empty phase-4b stubs.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

SCHEMA_VERSION = 1


class UniverseEntry(BaseModel):
    """One active instrument in a market snapshot.

    Attributes:
        symbol: Ticker symbol as stored in theeyebeta.instruments.
        instrument_id: PK from theeyebeta.instruments.
        sector: GICS sector string, or None if not classified.
        industry: GICS industry string, or None if not classified.
    """

    model_config = ConfigDict(extra="forbid")

    symbol: str
    instrument_id: int
    sector: str | None
    industry: str | None


class PriceBlock(BaseModel):
    """OHLCV data for one instrument on the snapshot date.

    Attributes:
        open: Opening price (unadjusted).
        high: Intraday high (unadjusted).
        low: Intraday low (unadjusted).
        close: Closing price (unadjusted).
        adj_close: Dividend/split-adjusted closing price, or None if unavailable.
        volume: Share volume traded.
    """

    model_config = ConfigDict(extra="forbid")

    open: float
    high: float
    low: float
    close: float
    adj_close: float | None
    volume: int


class TechnicalsBlock(BaseModel):
    """Technical indicators computed over the 250-bar rolling window.

    All values may be None when the window is shorter than the indicator's
    minimum required periods (e.g. SMA200 requires at least 200 bars).

    Attributes:
        atr14: 14-period Average True Range using the unadjusted close.
        rsi14: 14-period Relative Strength Index (simple MA variant); 0–100.
        zscore20: Z-score of adj_close relative to its 20-period mean/std.
        bb_upper20_2: Bollinger upper band (SMA20 + 2σ).
        bb_lower20_2: Bollinger lower band (SMA20 − 2σ).
        sma20: 20-period simple moving average of adj_close.
        sma50: 50-period simple moving average of adj_close.
        sma200: 200-period simple moving average of adj_close.
    """

    model_config = ConfigDict(extra="forbid")

    atr14: float | None
    rsi14: float | None
    zscore20: float | None
    bb_upper20_2: float | None
    bb_lower20_2: float | None
    sma20: float | None
    sma50: float | None
    sma200: float | None


class Snapshot(BaseModel):
    """A complete market-data snapshot for one exchange on one trading date.

    Attributes:
        schema_version: Integer version of this contract (currently 1).
        market: MIC exchange code (e.g. "XNAS").
        snapshot_id: UUID generated at package time — uniquely identifies this run.
        as_of: UTC datetime representing the end-of-day moment for trade_date.
        trade_date: ISO date string "YYYY-MM-DD".
        universe: Ordered list of active instruments in this market.
        prices: Mapping symbol → PriceBlock for the trade_date bar.
        technicals: Mapping symbol → TechnicalsBlock computed over 250 bars.
        macro: Mapping FRED series_code → latest observed value.
        news_summary: Phase 4b placeholder (empty list until news ingestion).
        fundamentals: Phase 4b placeholder (empty dict until fundamentals ingestion).
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: int = Field(default=SCHEMA_VERSION)
    market: str
    snapshot_id: UUID
    as_of: datetime
    trade_date: str  # YYYY-MM-DD
    universe: list[UniverseEntry]
    prices: dict[str, PriceBlock]
    technicals: dict[str, TechnicalsBlock]
    macro: dict[str, float]
    news_summary: list = Field(default_factory=list)  # Phase 4b
    fundamentals: dict = Field(default_factory=dict)  # Phase 4b
