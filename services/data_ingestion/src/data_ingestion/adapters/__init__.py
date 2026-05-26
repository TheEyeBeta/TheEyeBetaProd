"""Data-ingestion adapter registry."""

from __future__ import annotations

from collections.abc import Callable

from data_ingestion.adapters.alpaca_data import AlpacaDataAdapter
from data_ingestion.adapters.base import DataAdapter
from data_ingestion.adapters.cn_proxy import CnProxyAdapter
from data_ingestion.adapters.fred import FredAdapter
from data_ingestion.adapters.news import NewsAdapter
from data_ingestion.adapters.yfinance import YfinanceAdapter

_ADAPTER_FACTORIES: dict[str, Callable[[], DataAdapter]] = {
    "yfinance": YfinanceAdapter,
    "fred": FredAdapter,
    "alpaca_data": AlpacaDataAdapter,
    "cn_proxy": CnProxyAdapter,
    "news": NewsAdapter,
}

_ALIASES: dict[str, str] = {
    "prices": "yfinance",
    "price": "yfinance",
    "macro": "fred",
    "alpaca": "alpaca_data",
    "cn": "cn_proxy",
}


def resolve_adapter_name(name: str | None) -> list[str]:
    """Resolve adapter query value to canonical adapter names."""
    if name is None or name.lower() in {"", "all"}:
        return list(_ADAPTER_FACTORIES)
    key = _ALIASES.get(name.lower(), name.lower())
    if key not in _ADAPTER_FACTORIES:
        raise ValueError(f"Unknown adapter: {name!r}")
    return [key]


def get_adapter(name: str) -> DataAdapter:
    """Instantiate an adapter by canonical name."""
    canonical = _ALIASES.get(name.lower(), name.lower())
    factory = _ADAPTER_FACTORIES.get(canonical)
    if factory is None:
        raise ValueError(f"Unknown adapter: {name!r}")
    return factory()


__all__ = [
    "AlpacaDataAdapter",
    "CnProxyAdapter",
    "DataAdapter",
    "FredAdapter",
    "NewsAdapter",
    "YfinanceAdapter",
    "get_adapter",
    "resolve_adapter_name",
]
