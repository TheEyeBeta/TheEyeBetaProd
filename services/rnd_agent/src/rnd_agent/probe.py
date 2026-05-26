"""Startup probe verifying ``tb_rnd_readonly`` cannot read/write forbidden tables."""

from __future__ import annotations

import psycopg
import structlog

log = structlog.get_logger()


class ReadonlyRoleProbeError(RuntimeError):
    """Raised when the R&D DB role has excessive privileges."""


def verify_readonly_role(dsn: str) -> None:
    """Assert UPDATE on ``instruments`` and SELECT on ``audit_log`` both fail.

    Args:
        dsn: Connection string for ``tb_rnd_readonly`` (``RND_DATABASE_URL``).

    Raises:
        ReadonlyRoleProbeError: If either forbidden operation succeeds.
    """
    failures: list[str] = []
    async_errors: list[str] = []

    with psycopg.connect(dsn, autocommit=True) as conn:
        try:
            conn.execute(
                "UPDATE theeyebeta.instruments SET symbol = symbol WHERE id = 1",
            )
            failures.append("UPDATE on theeyebeta.instruments succeeded (must be denied)")
        except psycopg.errors.InsufficientPrivilege:
            log.info("rnd_probe_instruments_update_denied")
        except Exception as exc:  # noqa: BLE001
            async_errors.append(f"instruments UPDATE: {exc}")

        try:
            conn.execute("SELECT id FROM theeyebeta.audit_log LIMIT 1")
            failures.append("SELECT on theeyebeta.audit_log succeeded (must be denied)")
        except psycopg.errors.InsufficientPrivilege:
            log.info("rnd_probe_audit_log_select_denied")
        except Exception as exc:  # noqa: BLE001
            async_errors.append(f"audit_log SELECT: {exc}")

    if failures:
        joined = "; ".join(failures)
        msg = f"RND readonly role probe FAILED — tb_rnd_readonly has forbidden privileges. {joined}"
        raise ReadonlyRoleProbeError(msg)

    if async_errors:
        msg = f"RND readonly role probe could not verify privileges: {'; '.join(async_errors)}"
        raise ReadonlyRoleProbeError(msg)

    log.info("rnd_readonly_role_probe_passed")
