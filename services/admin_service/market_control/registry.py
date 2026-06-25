"""Market data control gaps and provider catalog."""

from __future__ import annotations

from dataclasses import dataclass

STALE_DATASET_DAYS = 2

PROVIDERS: list[dict[str, str]] = [
    {"id": "massive", "title": "Massive.com ingest", "port": "7010", "worker": "massive-ingest"},
    {"id": "yfinance", "title": "YFinance adapter", "port": "7010", "worker": "daily-pipeline"},
    {"id": "fred", "title": "FRED macro", "port": "7010", "worker": "macro"},
    {"id": "alpaca", "title": "Alpaca intraday", "port": "7010", "worker": "intraday-ingest"},
    {"id": "snapshot-packager", "title": "Snapshot packager", "port": "7011", "worker": "snapshot-packager"},
    {"id": "data-api", "title": "Data API", "port": "7000", "worker": "theeyebeta-dataapi"},
]

DATA_API_PUBLIC_HOSTS: tuple[str, ...] = (
    "dataapi.theeyebeta.store",
    "dataapiprod.theeyebeta.store",
)


@dataclass(frozen=True, slots=True)
class MarketControlGap:
    action: str
    reason: str


BACKFILL_AUTH_GAP = MarketControlGap(
    action="backfill",
    reason=(
        "Backfill proxies data-ingestion POST /ingest/run; "
        "service requires HTTP Basic auth not stored in admin-service."
    ),
)

UNIVERSE_EDIT_GAP = MarketControlGap(
    action="change_universe",
    reason="Universe expansion uses scripts/expand_universe.py; no admin mutation API yet.",
)

MARKET_CAP_EVENTS_GAP = MarketControlGap(
    action="market_cap_events",
    reason="Market cap threshold events derived from corporate_actions; no dedicated events table.",
)

GAP_TABLE_GAP = MarketControlGap(
    action="audit_data_gaps",
    reason="Gap rows live in public.audit_data_gaps (legacy schema); resolve updates that table directly.",
)
