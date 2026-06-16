"""Worker registry, run history, and manual trigger APIs."""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime

import asyncpg
import structlog
from audit_log import write_audit_log
from deps import DbConn, SettingsDep
from fastapi import APIRouter, HTTPException, Query, Request, status
from lib.worker_registry import (
    WORKER_CLASS_NAMES,
    WORKER_MODULES,
)
from rbac import Role, require_role
from settings import Settings
from slowapi import Limiter

from zinc_schemas.admin_dto import (
    WorkerRegistryEntry,
    WorkerRunHistoryEntry,
    WorkerRunRequest,
    WorkerRunResponse,
    WorkerRunsResponse,
    WorkersListResponse,
)

log = structlog.get_logger()

router = APIRouter(prefix="/workers", tags=["workers"])


def _actor(user: dict[str, str]) -> str:
    return f"admin-api:{user['sub']}"


def _resolve_worker(name: str) -> tuple[str, str, str]:
    """Map API worker name to alias, module, and DB class name."""
    if name in WORKER_MODULES:
        alias = name
    else:
        alias = None
        for key, class_name in WORKER_CLASS_NAMES.items():
            if class_name == name or key == name:
                alias = key
                break
    if alias is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown worker {name!r}",
        )
    return alias, WORKER_MODULES[alias], WORKER_CLASS_NAMES[alias]


async def fetch_workers_registry(conn: asyncpg.Connection) -> list[WorkerRegistryEntry]:
    """Build worker registry from heartbeats, runs, and breakers."""
    hb_rows = await conn.fetch(
        """
        SELECT worker_id, status, last_heartbeat
          FROM theeyebeta.worker_heartbeats
         ORDER BY worker_id
        """,
    )
    hb_map = {row["worker_id"]: row for row in hb_rows}

    run_rows = await conn.fetch(
        """
        SELECT DISTINCT ON (worker_name)
               worker_name, status, started_at
          FROM theeyebeta.worker_runs
         ORDER BY worker_name, started_at DESC
        """,
    )
    run_map = {row["worker_name"]: row for row in run_rows}

    breaker_rows = await conn.fetch(
        """
        SELECT component_id, state
          FROM theeyebeta.trask_circuit_breakers
        """,
    )
    breaker_map = {row["component_id"]: row["state"] for row in breaker_rows}

    trask_rows = await conn.fetch(
        """
        SELECT component_id, state, last_heartbeat
          FROM theeyebeta.trask_components
         WHERE component_type = 'worker'
        """,
    )
    trask_map = {row["component_id"]: row for row in trask_rows}

    entries: list[WorkerRegistryEntry] = []
    seen: set[str] = set()

    for alias, class_name in WORKER_CLASS_NAMES.items():
        seen.add(class_name)
        hb = hb_map.get(class_name)
        run = run_map.get(class_name)
        trask = trask_map.get(class_name)
        sentinel_id = f"{class_name}_sentinel"
        entries.append(
            WorkerRegistryEntry(
                name=class_name,
                alias=alias,
                worker_class=class_name,
                state=(trask["state"] if trask else "UNKNOWN"),
                last_heartbeat=(hb["last_heartbeat"] if hb else None),
                last_run_status=(run["status"] if run else None),
                last_run_at=(run["started_at"] if run else None),
                next_scheduled_fire=None,
                circuit_breaker_state=breaker_map.get(sentinel_id),
            ),
        )

    for worker_id, hb in hb_map.items():
        if worker_id in seen:
            continue
        run = run_map.get(worker_id)
        trask = trask_map.get(worker_id)
        sentinel_id = f"{worker_id}_sentinel"
        entries.append(
            WorkerRegistryEntry(
                name=worker_id,
                alias=None,
                worker_class=worker_id,
                state=(trask["state"] if trask else hb["status"].upper()),
                last_heartbeat=hb["last_heartbeat"],
                last_run_status=(run["status"] if run else None),
                last_run_at=(run["started_at"] if run else None),
                next_scheduled_fire=None,
                circuit_breaker_state=breaker_map.get(sentinel_id),
            ),
        )

    entries.sort(key=lambda e: e.name)
    return entries


async def fetch_worker_runs_page(
    conn: asyncpg.Connection,
    *,
    worker_name: str | None,
    status_filter: str | None,
    from_date: date | None,
    to_date: date | None,
    limit: int,
    offset: int,
) -> tuple[list[WorkerRunHistoryEntry], int]:
    """Paginated worker run history."""
    clauses = ["1=1"]
    params: list[object] = []
    idx = 1

    if worker_name:
        clauses.append(f"worker_name = ${idx}")
        params.append(worker_name)
        idx += 1
    if status_filter:
        clauses.append(f"status = ${idx}")
        params.append(status_filter)
        idx += 1
    if from_date:
        clauses.append(f"trade_date >= ${idx}")
        params.append(from_date)
        idx += 1
    if to_date:
        clauses.append(f"trade_date <= ${idx}")
        params.append(to_date)
        idx += 1

    where = " AND ".join(clauses)
    total = await conn.fetchval(
        f"SELECT COUNT(*)::int FROM theeyebeta.worker_runs WHERE {where}",  # noqa: S608
        *params,
    )
    params.extend([limit, offset])
    rows = await conn.fetch(
        f"""
        SELECT run_id, worker_name, trade_date, run_type, status,
               started_at, ended_at, records_written, error_message
          FROM theeyebeta.worker_runs
         WHERE {where}
         ORDER BY started_at DESC
         LIMIT ${idx} OFFSET ${idx + 1}
        """,  # noqa: S608
        *params,
    )
    entries = [WorkerRunHistoryEntry(**dict(row)) for row in rows]
    return entries, int(total or 0)


async def trigger_worker_run(
    *,
    alias: str,
    module: str,
    class_name: str,
    body: WorkerRunRequest,
    settings: Settings,
    conn: asyncpg.Connection,
    actor: str,
) -> WorkerRunResponse:
    """Spawn a worker subprocess and record audit attribution."""
    repo_root = settings.repo_root_path()
    cmd = ["uv", "run", "python", "-m", module, "--run-type", "manual"]
    if body.dry_run:
        cmd.append("--dry-run")
    if body.force:
        cmd.append("--force")
    trade_date = body.args.get("date")
    if trade_date:
        cmd.extend(["--date", str(trade_date)])

    triggered_at = datetime.now(tz=UTC)
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=str(repo_root),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    exit_code = proc.returncode

    run_row = await conn.fetchrow(
        """
        SELECT run_id, status
          FROM theeyebeta.worker_runs
         WHERE worker_name = $1
         ORDER BY started_at DESC
         LIMIT 1
        """,
        class_name,
    )
    run_id = int(run_row["run_id"]) if run_row else None
    run_status = str(run_row["status"]) if run_row else ("FAILED" if exit_code else "UNKNOWN")

    audit_payload = {
        "actor": actor,
        "worker_name": class_name,
        "alias": alias,
        "dry_run": body.dry_run,
        "force": body.force,
        "args": body.args,
        "reason": body.reason,
        "triggered_at": triggered_at.isoformat(),
        "run_id": run_id,
        "exit_code": exit_code,
        "stderr_tail": stderr.decode(errors="replace")[-500:] if stderr else None,
        "override": False,
    }
    await write_audit_log(
        conn,
        actor=actor,
        action="trigger.worker",
        entity_type="worker",
        entity_id=class_name,
        payload=audit_payload,
    )

    if exit_code and exit_code != 0 and not body.dry_run:
        log.warning(
            "worker_manual_run_failed",
            worker=class_name,
            exit_code=exit_code,
            run_id=run_id,
        )

    return WorkerRunResponse(
        worker_name=class_name,
        triggered_at=triggered_at,
        run_id=run_id,
        exit_code=exit_code,
        status=run_status,
    )


def register_workers_routes(limiter: Limiter) -> APIRouter:
    """Attach worker read/control handlers."""

    @router.get(
        "",
        response_model=WorkersListResponse,
        summary="Worker registry (OPERATOR read)",
    )
    async def list_workers(
        conn: DbConn,
        user: dict[str, str] = require_role(Role.READ_ONLY),
    ) -> WorkersListResponse:
        """Return worker registry with heartbeat, run, and breaker state."""
        workers = await fetch_workers_registry(conn)
        log.info("admin_workers_listed", count=len(workers), sub=user["sub"])
        return WorkersListResponse(workers=workers, total=len(workers))

    @router.get(
        "/runs",
        response_model=WorkerRunsResponse,
        summary="Worker run history (OPERATOR read)",
    )
    async def list_worker_runs(
        conn: DbConn,
        user: dict[str, str] = require_role(Role.READ_ONLY),
        worker_name: str | None = Query(default=None),
        status: str | None = Query(default=None, alias="status"),
        from_date: date | None = Query(default=None),
        to_date: date | None = Query(default=None),
        limit: int = Query(default=50, ge=1, le=500),
        offset: int = Query(default=0, ge=0),
    ) -> WorkerRunsResponse:
        """Return paginated worker run history."""
        runs, total = await fetch_worker_runs_page(
            conn,
            worker_name=worker_name,
            status_filter=status,
            from_date=from_date,
            to_date=to_date,
            limit=limit,
            offset=offset,
        )
        log.info("admin_worker_runs_listed", total=total, sub=user["sub"])
        return WorkerRunsResponse(runs=runs, limit=limit, offset=offset, total=total)

    @router.post(
        "/{name}/run",
        response_model=WorkerRunResponse,
        summary="Trigger manual worker run (OPERATOR)",
    )
    @limiter.limit("10/minute")
    async def run_worker(
        request: Request,  # noqa: ARG001
        name: str,
        body: WorkerRunRequest,
        conn: DbConn,
        settings: SettingsDep,
        user: dict[str, str] = require_role(Role.OPERATOR),
    ) -> WorkerRunResponse:
        """Trigger a manual worker run with durable audit attribution."""
        alias, module, class_name = _resolve_worker(name)
        actor = _actor(user)
        result = await trigger_worker_run(
            alias=alias,
            module=module,
            class_name=class_name,
            body=body,
            settings=settings,
            conn=conn,
            actor=actor,
        )
        log.info(
            "admin_worker_triggered",
            worker=class_name,
            run_id=result.run_id,
            sub=user["sub"],
        )
        return result

    return router
