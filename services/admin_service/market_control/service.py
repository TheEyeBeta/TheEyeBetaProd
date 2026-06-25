"""Market data / snapshot orchestration."""

from __future__ import annotations

import asyncio
import json
from typing import Any
from uuid import UUID

import httpx
import structlog
from audit_log import write_audit_log
from edge.probes import probe_http_health
from market_control.client import (
    build_snapshot,
    data_api_internal_health,
    data_api_public_route_health,
    data_ingestion_health,
    data_ingestion_metrics_state,
    snapshot_packager_health,
    trigger_backfill,
)
from market_control.registry import (
    BACKFILL_AUTH_GAP,
    DATA_API_PUBLIC_HOSTS,
    GAP_TABLE_GAP,
    MARKET_CAP_EVENTS_GAP,
    PROVIDERS,
    UNIVERSE_EDIT_GAP,
    MarketControlGap,
)
from market_control.repository import MarketRepository
from settings import Settings
from zinc_schemas.admin_dto import (
    MarketBackfillRequest,
    MarketBackfillResponse,
    MarketCapEventEntry,
    MarketCapEventsResponse,
    MarketControlGapEntry,
    MarketDataGapEntry,
    MarketDataGapListResponse,
    MarketDataGapResolveResponse,
    MarketDataProviderEntry,
    MarketDataProvidersResponse,
    MarketDataRouteHealthEntry,
    MarketDataStatusResponse,
    MarketDatasetFreshnessEntry,
    MarketUniverseResponse,
    SnapshotArtifactEntry,
    SnapshotArtifactsResponse,
    SnapshotBuildRequest,
    SnapshotBuildResponse,
    SnapshotDetailResponse,
    SnapshotListResponse,
    SnapshotSummaryEntry,
)

log = structlog.get_logger()


class MarketControlService:
    """Data quality visibility and controlled operator actions."""

    def __init__(self, conn: Any, settings: Settings) -> None:
        self._conn = conn
        self._settings = settings
        self._repo = MarketRepository(conn)

    def _gaps(self) -> list[MarketControlGapEntry]:
        gaps: list[MarketControlGap] = [
            BACKFILL_AUTH_GAP,
            UNIVERSE_EDIT_GAP,
            MARKET_CAP_EVENTS_GAP,
            GAP_TABLE_GAP,
        ]
        return [MarketControlGapEntry(action=g.action, reason=g.reason) for g in gaps]

    async def _provider_health(self, provider_id: str, port: int) -> tuple[str, bool | None]:
        label, _ = await probe_http_health("127.0.0.1", port, "/health", timeout=1.0)
        reachable = label == "healthy"
        return ("ready" if reachable else label, reachable)

    async def get_status(self) -> MarketDataStatusResponse:
        gap_counts = await self._repo.gap_counts()
        freshness = await self._repo.dataset_freshness()
        universe = await self._repo.universe_stats()
        state = await self._repo.get_state()

        ingestion_health = "unknown"
        ingestion_reachable: bool | None = False
        try:
            await data_ingestion_health(self._settings)
            ingestion_health = "ready"
            ingestion_reachable = True
        except (httpx.HTTPError, OSError):
            ingestion_reachable = False

        packager_health = "unknown"
        packager_reachable: bool | None = False
        try:
            await snapshot_packager_health(self._settings)
            packager_health = "ready"
            packager_reachable = True
        except (httpx.HTTPError, OSError):
            packager_reachable = False

        data_api_label, _ = await data_api_internal_health(self._settings)
        public_routes: list[MarketDataRouteHealthEntry] = []
        for host in DATA_API_PUBLIC_HOSTS:
            probe = await data_api_public_route_health(host)
            public_routes.append(
                MarketDataRouteHealthEntry(
                    hostname=str(probe["hostname"]),
                    port=int(probe["port"]),
                    health=str(probe["health"]),
                    reachable=bool(probe["reachable"]),
                ),
            )

        stale_datasets = [row["dataset"] for row in freshness if row.get("stale")]

        return MarketDataStatusResponse(
            ingestion_health=ingestion_health,
            ingestion_reachable=ingestion_reachable,
            snapshot_packager_health=packager_health,
            snapshot_packager_reachable=packager_reachable,
            data_api_health=data_api_label,
            data_api_public_routes=public_routes,
            open_gap_count=gap_counts["open_total"],
            price_gap_count=gap_counts["price_open"],
            macro_gap_count=gap_counts["macro_open"],
            dataset_freshness=[
                MarketDatasetFreshnessEntry(
                    dataset=str(row["dataset"]),
                    latest_date=row.get("latest_date"),
                    stale=bool(row.get("stale")),
                )
                for row in freshness
            ],
            stale_datasets=stale_datasets,
            universe_size=int(universe["active_instruments"]),
            last_backfill_at=state.get("last_backfill_at"),
            last_backfill_by=state.get("last_backfill_by"),
            control_gaps=self._gaps(),
            checked_at=MarketRepository.utc_now(),
        )

    async def list_providers(self) -> MarketDataProvidersResponse:
        health_rows = await asyncio.gather(
            *[
                self._provider_health(str(item["id"]), int(item["port"]))
                for item in PROVIDERS
            ],
        )
        entries: list[MarketDataProviderEntry] = []
        for item, (health, reachable) in zip(PROVIDERS, health_rows, strict=True):
            port = int(item["port"])
            entries.append(
                MarketDataProviderEntry(
                    id=item["id"],
                    title=item["title"],
                    port=port,
                    worker=item.get("worker"),
                    health=health,
                    reachable=reachable,
                ),
            )
        return MarketDataProvidersResponse(providers=entries)

    async def list_gaps(self, *, limit: int = 50) -> MarketDataGapListResponse:
        rows = await self._repo.list_gaps(limit=limit)
        return MarketDataGapListResponse(
            gaps=[
                MarketDataGapEntry(
                    id=int(row["gap_id"]),
                    dataset_type=str(row["dataset_type"]),
                    trade_date=row["trade_date"],
                    severity=str(row["severity"]),
                    remediation_state=str(row["remediation_state"]),
                    remediation_notes=row.get("remediation_notes"),
                    expected_count=row.get("expected_count"),
                    actual_count=row.get("actual_count"),
                    updated_at=row.get("updated_at"),
                )
                for row in rows
            ],
        )

    async def resolve_gap(
        self,
        gap_id: int,
        *,
        actor: str,
        reason: str,
    ) -> MarketDataGapResolveResponse:
        row = await self._repo.resolve_gap(gap_id, note=reason, actor=actor)
        if row is None:
            msg = f"Gap {gap_id} not found or not OPEN"
            raise ValueError(msg)
        await self._repo.record_event(
            event_type="gap_resolve",
            actor=actor,
            reason=reason,
            payload={"gap_id": gap_id},
        )
        await write_audit_log(
            self._conn,
            actor=actor,
            action="market.gap.resolve",
            entity_type="data_gap",
            entity_id=str(gap_id),
            payload={"reason": reason},
        )
        return MarketDataGapResolveResponse(
            id=int(row["gap_id"]),
            dataset_type=str(row["dataset_type"]),
            remediation_state=str(row["remediation_state"]),
            audited=True,
            reason=reason,
        )

    async def backfill(
        self,
        body: MarketBackfillRequest,
        *,
        actor: str,
    ) -> MarketBackfillResponse:
        trading_date = body.trading_date.isoformat() if body.trading_date else None
        mode = "remote"
        result: dict[str, object]
        try:
            result = await trigger_backfill(
                self._settings,
                adapter=body.adapter,
                trading_date=trading_date,
            )
            if result.get("status") == "auth_required":
                mode = "auth_gap"
        except (httpx.HTTPError, OSError) as exc:
            mode = "unreachable"
            result = {"error": str(exc)[:200]}
        await self._repo.save_state(
            last_backfill_at=MarketRepository.utc_now(),
            last_backfill_by=actor,
        )
        await self._repo.record_event(
            event_type="backfill",
            actor=actor,
            reason=body.reason,
            payload={"mode": mode, "adapter": body.adapter},
        )
        await write_audit_log(
            self._conn,
            actor=actor,
            action="market.backfill",
            entity_type="market_data",
            entity_id=body.adapter or "all",
            payload={"reason": body.reason, "mode": mode},
        )
        return MarketBackfillResponse(
            mode=mode,
            result=result,
            audited=True,
            reason=body.reason,
        )

    async def get_universe(self) -> MarketUniverseResponse:
        stats = await self._repo.universe_stats()
        return MarketUniverseResponse(
            active_instruments=int(stats["active_instruments"]),
            exchange_count=int(stats["exchange_count"]),
            editable=False,
            control_gaps=[
                MarketControlGapEntry(action=UNIVERSE_EDIT_GAP.action, reason=UNIVERSE_EDIT_GAP.reason),
            ],
        )

    async def market_cap_events(self, *, limit: int = 20) -> MarketCapEventsResponse:
        rows = await self._repo.market_cap_events(limit=limit)
        return MarketCapEventsResponse(
            events=[
                MarketCapEventEntry(
                    id=int(row["id"]),
                    symbol=str(row["symbol"]),
                    action_type=str(row["action_type"]),
                    ex_date=row.get("ex_date"),
                    amount=float(row["amount"]) if row.get("amount") is not None else None,
                )
                for row in rows
            ],
            control_gaps=[
                MarketControlGapEntry(
                    action=MARKET_CAP_EVENTS_GAP.action,
                    reason=MARKET_CAP_EVENTS_GAP.reason,
                ),
            ],
        )

    async def list_snapshots(self, *, limit: int = 50) -> SnapshotListResponse:
        rows = await self._repo.list_snapshots(limit=limit)
        latest = rows[0] if rows else None
        return SnapshotListResponse(
            snapshots=[
                SnapshotSummaryEntry(
                    id=str(row["id"]),
                    snapshot_id=str(row["snapshot_id"]),
                    market=str(row["market"]),
                    trade_date=row["trade_date"],
                    universe_size=int(row["universe_size"]),
                    packaged_at=row["packaged_at"],
                )
                for row in rows
            ],
            latest_market=str(latest["market"]) if latest else None,
            latest_trade_date=latest["trade_date"] if latest else None,
        )

    async def get_snapshot(self, snapshot_id: UUID) -> SnapshotDetailResponse:
        row = await self._repo.get_snapshot(snapshot_id)
        if row is None:
            msg = f"Snapshot {snapshot_id} not found"
            raise ValueError(msg)
        return SnapshotDetailResponse(
            id=str(row["id"]),
            snapshot_id=str(row["snapshot_id"]),
            market=str(row["market"]),
            trade_date=row["trade_date"],
            schema_version=int(row["schema_version"]),
            blob_uri=str(row["blob_uri"]),
            blob_sha256=str(row.get("blob_sha256") or ""),
            universe_size=int(row["universe_size"]),
            packaged_at=row["packaged_at"],
            packager_git_sha=row.get("packager_git_sha"),
        )

    async def snapshot_artifacts(self, snapshot_id: UUID) -> SnapshotArtifactsResponse:
        artifacts = await self._repo.snapshot_artifacts(snapshot_id)
        return SnapshotArtifactsResponse(
            snapshot_id=str(snapshot_id),
            artifacts=[
                SnapshotArtifactEntry(
                    kind=str(item["kind"]),
                    uri=str(item["uri"]),
                    sha256=item.get("sha256"),
                    universe_size=item.get("universe_size"),
                )
                for item in artifacts
            ],
        )

    async def build_snapshot(
        self,
        body: SnapshotBuildRequest,
        *,
        actor: str,
    ) -> SnapshotBuildResponse:
        mode = "remote"
        result: dict[str, object]
        try:
            result = await build_snapshot(
                self._settings,
                market=body.market,
                trading_date=body.trading_date.isoformat(),
            )
        except (httpx.HTTPError, OSError) as exc:
            mode = "unreachable"
            result = {"error": str(exc)[:200]}
            await self._repo.record_event(
                event_type="snapshot_build_failed",
                actor=actor,
                reason=body.reason,
                payload={"market": body.market, "error": str(exc)[:200]},
            )
            msg = "snapshot-packager unreachable"
            raise ValueError(msg) from exc
        await self._repo.save_state(
            last_snapshot_build_at=MarketRepository.utc_now(),
            last_snapshot_build_by=actor,
        )
        await self._repo.record_event(
            event_type="snapshot_build",
            actor=actor,
            reason=body.reason,
            payload={"market": body.market, "date": body.trading_date.isoformat(), "mode": mode},
        )
        await write_audit_log(
            self._conn,
            actor=actor,
            action="snapshot.build",
            entity_type="snapshot",
            entity_id=str(result.get("snapshot_id") or body.market),
            payload={"reason": body.reason, "market": body.market},
        )
        return SnapshotBuildResponse(
            market=str(result.get("market") or body.market),
            trade_date=str(result.get("date") or body.trading_date.isoformat()),
            snapshot_id=str(result.get("snapshot_id") or ""),
            blob_uri=str(result.get("blob_uri") or ""),
            sha256=str(result.get("sha256") or ""),
            universe_size=int(result.get("universe_size") or 0),
            mode=mode,
            audited=True,
            reason=body.reason,
        )

    async def recent_events(self, *, limit: int = 50) -> list[dict[str, Any]]:
        return await self._repo.list_history(limit=limit)

    async def pipeline_status(self) -> dict[str, Any]:
        workers = await self._repo.worker_run_summary()
        metrics: dict[str, object] = {}
        try:
            metrics = await data_ingestion_metrics_state(self._settings)
        except (httpx.HTTPError, OSError):
            metrics = {}
        return {"workers": workers, "ingestion_metrics": metrics}
