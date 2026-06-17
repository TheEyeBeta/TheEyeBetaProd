"""Prometheus metrics for audit-service."""

from __future__ import annotations

import psycopg
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Gauge,
    generate_latest,
)


class AuditMetrics:
    """Owns audit-service metrics in a per-app registry."""

    def __init__(self) -> None:
        self.registry = CollectorRegistry()
        self.audit_entries_total = Gauge(
            "audit_entries_total",
            "Total audit_log entries currently stored.",
            registry=self.registry,
        )
        self.chain_verification_status = Gauge(
            "chain_verification_status",
            "Latest audit chain verification status: 1=OK, 0=failed or unknown.",
            registry=self.registry,
        )
        self.events_consumed_total = Counter(
            "events_consumed_total",
            "Total JetStream audit events consumed by audit-service.",
            registry=self.registry,
        )

    async def refresh_from_db(self, dsn: str) -> None:
        """Refresh scrape-time gauges from Postgres."""
        async with await psycopg.AsyncConnection.connect(dsn) as conn:
            entries_cur = await conn.execute("SELECT count(*) FROM theeyebeta.audit_log")
            entries = await entries_cur.fetchone()
            self.audit_entries_total.set(int(entries[0]) if entries else 0)

            status_cur = await conn.execute(
                """
                SELECT valid
                  FROM theeyebeta.audit_chain_status
                 ORDER BY verified_at DESC, id DESC
                 LIMIT 1
                """,
            )
            status = await status_cur.fetchone()
            self.chain_verification_status.set(1 if status and status[0] else 0)

    def render(self) -> tuple[bytes, str]:
        """Return Prometheus exposition bytes and content type."""
        return generate_latest(self.registry), CONTENT_TYPE_LATEST
