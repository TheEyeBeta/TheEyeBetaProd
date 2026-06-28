"""Trask worker id → systemd unit mapping for prod CLI control."""

from __future__ import annotations

TRASK_WORKER_UNITS: dict[str, str] = {
    "price": "theeye-massive-ingest.service",
    "massive": "theeye-massive-ingest.service",
    "massive-ingest": "theeye-massive-ingest.service",
    "news": "theeye-news-ingest.service",
    "news-ingest": "theeye-news-ingest.service",
    "indicator": "theeye-daily-pipeline.service",
    "intraday": "theeye-intraday-ingest.service",
    "macro": "theeye-macro.service",
    "sector": "theeye-sector.service",
    "gap": "theeye-gap-sentinel.service",
    "gap-sentinel": "theeye-gap-sentinel.service",
    "daily-pipeline": "theeye-daily-pipeline.service",
    "pipeline": "theeye-daily-pipeline.service",
}


def resolve_worker_unit(worker_id: str) -> str | None:
    """Map a Trask worker id to a prod systemd unit."""
    key = worker_id.lower().replace("_", "-")
    return TRASK_WORKER_UNITS.get(key)
