"""Unit tests for the RSS news adapter (VCR-recorded HTTP)."""

from __future__ import annotations

from datetime import date
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from data_ingestion.adapters.news import NewsAdapter

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
    with patch("data_ingestion.adapters.news.make_http_client", return_value=mock_client):
        records = [record async for record in adapter.fetch(target)]

    assert len(records) == 1
    assert records[0].record_type == "news"
    assert records[0].headline == "Sample headline"
    assert len(records[0].url_hash) == 64
