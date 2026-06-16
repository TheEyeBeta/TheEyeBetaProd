"""Admin SQL router — read-only SELECT queries + confirmed write executions."""

from __future__ import annotations

import asyncio
import re
import time
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

import asyncpg
import sqlparse
import structlog
from audit_log import write_audit_log
from deps import DbConn
from fastapi import APIRouter, Header, HTTPException, Request, status
from rbac import Role, require_role
from slowapi import Limiter
from sqlparse.sql import Statement
from sqlparse.tokens import DDL, DML, Keyword

from zinc_schemas.admin_dto import (
    SqlExecuteRequest,
    SqlExecuteResponse,
    SqlQueryRequest,
    SqlQueryResponse,
)

log = structlog.get_logger()

router = APIRouter(prefix="/sql", tags=["sql"])

_QUERY_TIMEOUT_SECONDS = 30.0
_QUERY_MAX_ROWS = 1000

_BLOCKED_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.IGNORECASE)
    for p in (
        r"\bDROP\b",
        r"\bTRUNCATE\b",
        r"\bALTER\b",
        r"\bCREATE\b",
        r"\bDELETE\s+FROM\s+audit",
        r"\bUPDATE\s+audit",
        r"\bDELETE\s+FROM\s+admin_users",
        r"\bUPDATE\s+admin_users",
        r"\bpg_read_file\b",
        r"\bpg_ls_dir\b",
        r"\bCOPY\b",
        r"\bcreate_extension\b",
        r"--.*secret",
        r"--.*password",
    )
)

# DML/DDL keywords forbidden in /query (anything that mutates state).
_FORBIDDEN_QUERY_KEYWORDS: frozenset[str] = frozenset(
    {
        "INSERT",
        "UPDATE",
        "DELETE",
        "DROP",
        "TRUNCATE",
        "ALTER",
        "CREATE",
        "GRANT",
        "REVOKE",
        "COPY",
        "VACUUM",
        "REINDEX",
        "MERGE",
        "CALL",
    },
)

# Tables /execute is forbidden from touching at SQL layer (defense-in-depth on
# top of role grants — admin connects as ``tb_app`` which already lacks DELETE
# on these, but we reject early with 422).
_PROTECTED_TABLES: frozenset[str] = frozenset(
    {
        "audit_log",
        "audit_checkpoints",
        "proposals",
        "admin_users",
    },
)


def _check_blocked_patterns(statement: str) -> None:
    """Reject dangerous SQL patterns before execution."""
    for pattern in _BLOCKED_PATTERNS:
        if pattern.search(statement):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Blocked SQL pattern: {pattern.pattern}",
            )


async def _apply_sql_guardrails(conn: asyncpg.Connection) -> None:
    """Set per-statement Postgres limits for SQL console."""
    await conn.execute("SET LOCAL statement_timeout = '30s'")
    await conn.execute("SET LOCAL work_mem = '16MB'")


def _actor(user: dict[str, str]) -> str:
    """Build audit actor string from JWT subject."""
    return f"admin-api:{user['sub']}"
    """Build audit actor string from JWT subject."""
    return f"admin-api:{user['sub']}"


# Public aliases (used by the HTML view layer to bypass HTTP self-loops).
QUERY_TIMEOUT_SECONDS = _QUERY_TIMEOUT_SECONDS
QUERY_MAX_ROWS = _QUERY_MAX_ROWS


def _parse_one(statement: str) -> Statement:
    """Parse exactly one SQL statement and reject batches/empties."""
    parsed = [s for s in sqlparse.parse(statement) if s.tokens and str(s).strip()]
    if not parsed:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Empty SQL statement",
        )
    if len(parsed) > 1:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Multiple statements are not allowed",
        )
    return parsed[0]


def _statement_keywords(stmt: Statement) -> set[str]:
    """Return upper-cased DML/DDL keywords found anywhere in ``stmt``."""
    keywords: set[str] = set()
    for token in stmt.flatten():
        if token.ttype in (DML, DDL, Keyword.DML, Keyword.DDL):
            keywords.add(token.value.upper())
    return keywords


def _validate_select_only(statement: str) -> Statement:
    """Ensure ``statement`` is a single read-only SELECT/WITH expression."""
    _check_blocked_patterns(statement)
    stmt = _parse_one(statement)
    stmt_type = (stmt.get_type() or "").upper()
    if stmt_type not in {"SELECT", "UNKNOWN"}:
        # ``UNKNOWN`` covers ``WITH`` CTEs that ultimately SELECT.
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Only SELECT statements are allowed (got {stmt_type})",
        )
    keywords = _statement_keywords(stmt)
    forbidden = keywords & _FORBIDDEN_QUERY_KEYWORDS
    if forbidden:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Forbidden keyword in /query: {sorted(forbidden)}",
        )
    if stmt_type == "UNKNOWN":
        # Accept only WITH ... SELECT.
        first_token = next(
            (t for t in stmt.tokens if not t.is_whitespace),
            None,
        )
        if first_token is None or first_token.value.upper() != "WITH":
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Only SELECT or WITH...SELECT statements are allowed",
            )
    return stmt


def _validate_execute(statement: str) -> Statement:
    """Reject empty / multi-statement / protected-table writes."""
    _check_blocked_patterns(statement)
    stmt = _parse_one(statement)
    lowered = statement.lower()
    for table in _PROTECTED_TABLES:
        if table in lowered:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Statement may not reference protected table '{table}'",
            )
    return stmt


def _json_safe(value: object) -> object:
    """Recursively coerce DB values into JSON-serialisable primitives."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, (bytes, bytearray, memoryview)):
        return bytes(value).hex()
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_json_safe(v) for v in value]
    return str(value)


def _row_values(row: asyncpg.Record) -> list[object]:
    """Convert one Record into an ordered list of JSON-safe primitives."""
    return [_json_safe(row[col]) for col in row.keys()]  # noqa: SIM118


# ---------------------------------------------------------------------------
# Public helpers (consumed by ``api/views.py`` to keep the HTML page in sync
# with the JSON router without HTTP self-loops).
# ---------------------------------------------------------------------------


validate_select_only = _validate_select_only
validate_execute = _validate_execute
json_safe = _json_safe


async def run_select_statement(
    conn: asyncpg.Connection,
    statement: str,
    parameters: list[object] | tuple[object, ...] | None = None,
) -> SqlQueryResponse:
    """Validate + execute a read-only SELECT, returning the typed response.

    Raises ``HTTPException`` (422 for invalid syntax / forbidden keyword,
    504 on timeout) so the caller — whether the JSON closure or the HTML
    fragment — gets identical semantics.
    """
    _validate_select_only(statement)
    params = list(parameters or [])
    started = time.perf_counter()
    try:
        async with conn.transaction():
            await _apply_sql_guardrails(conn)
            rows = await asyncio.wait_for(
                conn.fetch(statement, *params),
                timeout=_QUERY_TIMEOUT_SECONDS,
            )
    except TimeoutError as exc:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail=f"Query exceeded {_QUERY_TIMEOUT_SECONDS:.0f}s",
        ) from exc
    except asyncpg.PostgresError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    elapsed_ms = int((time.perf_counter() - started) * 1000)
    truncated = len(rows) > _QUERY_MAX_ROWS
    returned = rows[:_QUERY_MAX_ROWS]
    columns = list(returned[0].keys()) if returned else []
    json_rows = [_row_values(row) for row in returned]
    return SqlQueryResponse(
        columns=columns,
        rows=json_rows,
        row_count=len(json_rows),
        truncated=truncated,
        elapsed_ms=elapsed_ms,
    )


async def run_write_statement(
    conn: asyncpg.Connection,
    statement: str,
    parameters: list[object] | tuple[object, ...] | None = None,
    *,
    actor: str,
    idempotency_key: str,
) -> SqlExecuteResponse:
    """Validate + execute a write statement within a transaction.

    Writes the ``execute.sql`` audit log row in the same transaction so the
    statement and its parameters land atomically with the side effects.
    Raises the same ``HTTPException`` shapes as the JSON closure.
    """
    if not idempotency_key or not idempotency_key.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="X-Idempotency-Key header is required",
        )
    _validate_execute(statement)
    params = list(parameters or [])
    audit_payload = {
        "statement": statement,
        "parameters": [_json_safe(p) for p in params],
        "idempotency_key": idempotency_key,
    }

    started = time.perf_counter()
    try:
        async with conn.transaction():
            await _apply_sql_guardrails(conn)
            command_tag = await asyncio.wait_for(
                conn.execute(statement, *params),
                timeout=_QUERY_TIMEOUT_SECONDS,
            )
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            rows_affected = _command_tag_rows(command_tag)
            await write_audit_log(
                conn,
                actor=actor,
                action="execute.sql",
                entity_type="sql",
                entity_id=idempotency_key,
                payload={
                    **audit_payload,
                    "elapsed_ms": elapsed_ms,
                    "rows_affected": rows_affected,
                },
            )
    except TimeoutError as exc:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail=f"Statement exceeded {_QUERY_TIMEOUT_SECONDS:.0f}s",
        ) from exc
    except asyncpg.InsufficientPrivilegeError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(exc),
        ) from exc
    except asyncpg.PostgresError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    elapsed_ms = int((time.perf_counter() - started) * 1000)
    rows_affected = _command_tag_rows(command_tag)
    return SqlExecuteResponse(
        command_tag=command_tag,
        rows_affected=rows_affected,
        elapsed_ms=elapsed_ms,
        idempotency_key=idempotency_key,
    )


def register_sql_routes(limiter: Limiter) -> APIRouter:
    """Attach rate-limited SQL handlers."""

    @router.post("/query", response_model=SqlQueryResponse)
    @limiter.limit("20/minute")
    async def run_query(
        request: Request,  # noqa: ARG001 — required by slowapi
        body: SqlQueryRequest,
        conn: DbConn,
        user: dict[str, str] = require_role(Role.ANALYST),
    ) -> SqlQueryResponse:
        """Execute a read-only SELECT and return rows + columns (ANALYST minimum)."""
        response = await run_select_statement(conn, body.statement, body.parameters)
        log.info(
            "admin_sql_query",
            sub=user["sub"],
            row_count=response.row_count,
            truncated=response.truncated,
            elapsed_ms=response.elapsed_ms,
        )
        return response

    @router.post("/execute", response_model=SqlExecuteResponse)
    @limiter.limit("20/minute")
    async def run_execute(
        request: Request,  # noqa: ARG001 — required by slowapi
        body: SqlExecuteRequest,
        conn: DbConn,
        user: dict[str, str] = require_role(Role.MASTER_ADMIN),
        x_confirm: str | None = Header(default=None, alias="X-Confirm"),
        x_idempotency_key: str | None = Header(default=None, alias="X-Idempotency-Key"),
    ) -> SqlExecuteResponse:
        """Execute a write SQL statement after explicit confirmation (MASTER_ADMIN)."""
        if (x_confirm or "").lower() != "true":
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="X-Confirm: true header is required",
            )
        if not x_idempotency_key or not x_idempotency_key.strip():
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="X-Idempotency-Key header is required",
            )

        response = await run_write_statement(
            conn,
            body.statement,
            body.parameters,
            actor=_actor(user),
            idempotency_key=x_idempotency_key,
        )
        log.info(
            "admin_sql_execute",
            sub=user["sub"],
            command_tag=response.command_tag,
            rows_affected=response.rows_affected,
            elapsed_ms=response.elapsed_ms,
            idempotency_key=response.idempotency_key,
        )
        return response

    return router


def _command_tag_rows(tag: str) -> int:
    """Parse asyncpg command tag (``"UPDATE 3"``, ``"INSERT 0 1"``)."""
    parts = tag.split()
    if not parts:
        return 0
    try:
        return int(parts[-1])
    except ValueError:
        return 0
