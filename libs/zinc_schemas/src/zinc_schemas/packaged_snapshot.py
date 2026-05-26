"""Agent-ready packaged snapshot contract (schema v1)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

PACKAGED_SCHEMA_VERSION = 1


class PackagedUniverseEntry(BaseModel):
    """One instrument in a packaged snapshot universe."""

    model_config = ConfigDict(extra="forbid")

    symbol: str
    instrument_id: int
    sector: str | None = None
    industry: str | None = None


class PackagedPriceBar(BaseModel):
    """OHLCV block for one symbol on the snapshot date."""

    model_config = ConfigDict(extra="forbid")

    open: float
    high: float
    low: float
    close: float
    adj_close: float | None = None
    volume: int


class PackagedTechnicals(BaseModel):
    """Technical indicators for one symbol (last bar of the window)."""

    model_config = ConfigDict(extra="forbid")

    atr14: float | None = None
    adx14: float | None = None
    rsi14: float | None = None
    zscore20: float | None = None
    bb_upper20_2: float | None = None
    bb_lower20_2: float | None = None


class PackagedNewsItem(BaseModel):
    """News headline summary for agent consumption."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    headline: str
    tickers: list[str] = Field(default_factory=list)
    published_at: datetime


class PackagedSnapshotV1(BaseModel):
    """Agent-ready JSON snapshot for one market and trade date."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = PACKAGED_SCHEMA_VERSION
    market: str
    snapshot_id: UUID
    as_of: datetime
    universe: list[PackagedUniverseEntry]
    prices: dict[str, PackagedPriceBar]
    technicals: dict[str, PackagedTechnicals]
    macro: dict[str, float] = Field(default_factory=dict)
    news_summary: list[PackagedNewsItem] = Field(default_factory=list)
