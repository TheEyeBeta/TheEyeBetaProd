"""Prelive go/no-go check API."""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime, timedelta

import asyncpg
import structlog
from deps import DbConn, SettingsDep
from fastapi import APIRouter, Query
from rbac import Role, require_role
from settings import Settings

from zinc_schemas.admin_dto import PreliveCheckItem, PreliveResponse

log = structlog.get_logger()

router = APIRouter(prefix="/prelive", tags=["prelive"])

PRELIVE_STALE_HOURS = 6


def _ensure_prelive_import(settings: Settings) -> None:
    """Add repo root to ``sys.path`` for ``scripts.prelive_check``."""
    root = str(settings.repo_root_path())
    if root not in sys.path:
        sys.path.insert(0, root)


async def run_prelive_checks(settings: Settings) -> PreliveResponse:
    """Execute all prelive checks and return structured JSON."""
    _ensure_prelive_import(settings)
    from scripts.prelive_check import run_checks  # noqa: PLC0415

    results = await run_checks()
    run_at = datetime.now(tz=UTC)
    checks: list[PreliveCheckItem] = []
    for result in results:
        status_map = {"PASS": "pass", "FAIL": "fail", "WARN": "warn"}
        checks.append(
            PreliveCheckItem(
                name=result.name,
                status=status_map.get(result.status, result.status.lower()),
                detail=result.evidence,
                value=None,
            ),
        )
    fail_count = sum(1 for c in checks if c.status == "fail")
    overall = "pass" if fail_count == 0 else "fail"
    return PreliveResponse(
        overall=overall,
        run_at=run_at,
        is_stale=False,
        checks=checks,
    )


async def cache_prelive_result(conn: asyncpg.Connection, response: PreliveResponse) -> None:
    """Persist prelive result for ops pulse embedding."""
    checks_json = json.dumps([c.model_dump(mode="json") for c in response.checks])
    await conn.execute(
        """
        INSERT INTO theeyebeta.prelive_check_cache (run_at, overall, checks)
        VALUES ($1, $2, $3::jsonb)
        """,
        response.run_at,
        response.overall,
        checks_json,
    )


async def load_cached_prelive(conn: asyncpg.Connection) -> PreliveResponse | None:
    """Load the most recent cached prelive result."""
    row = await conn.fetchrow(
        """
        SELECT run_at, overall, checks
          FROM theeyebeta.prelive_check_cache
         ORDER BY run_at DESC
         LIMIT 1
        """,
    )
    if row is None:
        return None
    checks_raw = row["checks"]
    if isinstance(checks_raw, str):
        checks_raw = json.loads(checks_raw)
    checks = [PreliveCheckItem(**item) for item in checks_raw]
    run_at = row["run_at"]
    if run_at.tzinfo is None:
        run_at = run_at.replace(tzinfo=UTC)
    is_stale = datetime.now(tz=UTC) - run_at > timedelta(hours=PRELIVE_STALE_HOURS)
    overall = row["overall"]
    if is_stale and overall != "stale":
        overall = "stale"
    return PreliveResponse(
        overall=overall,
        run_at=run_at,
        is_stale=is_stale,
        checks=checks,
    )


def register_prelive_routes() -> APIRouter:
    """Attach prelive check handler."""

    @router.get(
        "",
        response_model=PreliveResponse,
        summary="Prelive checks (READ_ONLY)",
        description=(
            "Returns structured go/no-go checks. Use run=true to execute live checks; "
            "otherwise returns the last cached result with freshness indicator."
        ),
    )
    async def prelive_status(
        conn: DbConn,
        settings: SettingsDep,
        user: dict[str, str] = require_role(Role.READ_ONLY),
        run: bool = Query(default=False, description="Execute live checks"),
    ) -> PreliveResponse:
        """Return prelive check results (cached or live)."""
        if run:
            response = await run_prelive_checks(settings)
            await cache_prelive_result(conn, response)
            log.info("admin_prelive_run", overall=response.overall, sub=user["sub"])
            return response

        cached = await load_cached_prelive(conn)
        if cached is not None:
            log.info("admin_prelive_cached", overall=cached.overall, sub=user["sub"])
            return cached

        return PreliveResponse(
            overall="stale",
            run_at=None,
            is_stale=True,
            checks=[],
        )

    return router
