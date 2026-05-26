"""Pydantic record models for data-ingestion adapters."""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field


class RecordBase(BaseModel):
    """Common fields for all ingested records."""

    model_config = ConfigDict(frozen=True)

    source: str
    observed_at: datetime


class PriceDailyRecord(RecordBase):
    """Daily OHLCV bar for one instrument."""

    record_type: Literal["price_daily"] = "price_daily"
    instrument_id: int
    symbol: str
    exchange_code: str
    open: float
    high: float
    low: float
    close: float
    adj_close: float | None
    volume: int


class MacroRecord(RecordBase):
    """Macroeconomic series observation."""

    record_type: Literal["macro"] = "macro"
    series_code: str
    value: float


class IntradayBarRecord(RecordBase):
    """Intraday OHLCV bar (1- or 5-minute)."""

    record_type: Literal["intraday_bar"] = "intraday_bar"
    instrument_id: int
    symbol: str
    bar_seconds: int
    open: float
    high: float
    low: float
    close: float
    volume: int


class NewsRecord(RecordBase):
    """News article from an RSS feed."""

    record_type: Literal["news"] = "news"
    headline: str
    url: str
    url_hash: str
    feed_name: str
    body: str | None = None
    language: str = "en"
    tickers: tuple[str, ...] = Field(default_factory=tuple)


class NewsEmbeddingRecord(RecordBase):
    """Vector embedding for a news article."""

    record_type: Literal["news_embedding"] = "news_embedding"
    article_url: str
    model: str
    embedding: tuple[float, ...]


class FundamentalRecord(RecordBase):
    """Fundamental financial statement row."""

    record_type: Literal["fundamental"] = "fundamental"
    instrument_id: int
    period_end: date
    period_type: Literal["Q", "A", "TTM"]
    revenue: float | None = None
    net_income: float | None = None
    eps: float | None = None
    pe_ratio: float | None = None
    pb_ratio: float | None = None
    debt_to_equity: float | None = None
    roe: float | None = None
    gross_margin: float | None = None
    free_cash_flow: float | None = None
    raw: dict[str, object] = Field(default_factory=dict)


Record = Annotated[
    PriceDailyRecord
    | MacroRecord
    | IntradayBarRecord
    | NewsRecord
    | NewsEmbeddingRecord
    | FundamentalRecord,
    Field(discriminator="record_type"),
]
