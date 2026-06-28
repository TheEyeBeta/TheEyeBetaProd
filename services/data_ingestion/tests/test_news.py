"""Unit tests for the RSS news adapter (VCR-recorded HTTP)."""

from __future__ import annotations

from datetime import date
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from data_ingestion.adapters.news import NewsAdapter
from data_ingestion.adapters.news_tickers import extract_tickers

from .vcr_helpers import cassette_response


@pytest.mark.unit
@pytest.mark.asyncio
async def test_fetch_yields_deduplicated_news_records() -> None:
    status, body = cassette_response("news_reuters.yaml")
    target = date(2025, 1, 15)
    feeds = [
        {
            "name": "reuters",
            "url": "https://feeds.reuters.com/reuters/businessNews",
            "language": "en",
        }
    ]

    async def mock_get(url: str) -> httpx.Response:
        return httpx.Response(status, text=body, request=httpx.Request("GET", url))

    mock_client = AsyncMock()
    mock_client.get = mock_get
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    adapter = NewsAdapter(feeds=feeds)
    with (
        patch("data_ingestion.adapters.news.make_http_client", return_value=mock_client),
        patch("data_ingestion.adapters.news.load_active_instruments", AsyncMock(return_value=[])),
    ):
        records = [record async for record in adapter.fetch(target)]

    assert len(records) == 1
    assert records[0].record_type == "news"
    assert records[0].headline == "Sample headline"
    assert len(records[0].url_hash) == 64


@pytest.mark.unit
@pytest.mark.asyncio
async def test_fetch_yields_api_provider_news_with_tickers(monkeypatch: pytest.MonkeyPatch) -> None:
    target = date(2026, 6, 19)
    monkeypatch.setenv("FINNHUB_API_KEY", "test-key")
    monkeypatch.delenv("ALPHAVANTAGE_API_KEY", raising=False)
    monkeypatch.delenv("ALPHA_VANTAGE_API_KEY", raising=False)
    monkeypatch.delenv("NEWSAPI_API_KEY", raising=False)
    monkeypatch.delenv("NEWS_API_KEY", raising=False)
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)

    async def mock_get(url: str, params: dict[str, str] | None = None) -> httpx.Response:  # noqa: ARG001
        payload = [
            {
                "datetime": 1781874000,
                "headline": "Apple shares rise after analyst upgrade",
                "summary": "AAPL gained after a Wall Street upgrade.",
                "url": "https://example.test/finnhub/aapl-upgrade",
                "source": "Yahoo",
                "related": "AAPL",
            }
        ]
        return httpx.Response(200, json=payload, request=httpx.Request("GET", url))

    mock_client = AsyncMock()
    mock_client.get = mock_get
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    adapter = NewsAdapter(feeds=[])
    with (
        patch("data_ingestion.adapters.news.make_http_client", return_value=mock_client),
        patch(
            "data_ingestion.adapters.news.load_active_instruments",
            AsyncMock(return_value=[{"symbol": "AAPL"}]),
        ),
    ):
        records = [record async for record in adapter.fetch(target)]

    assert len(records) == 1
    assert records[0].feed_name == "finnhub:yahoo"
    assert records[0].tickers == ("AAPL",)


@pytest.mark.unit
def test_ticker_extraction_ignores_common_word_symbols() -> None:
    universe = {"A", "FOR", "ON", "AAPL", "MSFT"}
    assert extract_tickers("A test for Apple on Monday mentions AAPL and MSFT.", universe) == (
        "AAPL",
        "MSFT",
    )
