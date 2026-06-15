"""``tb meta`` — doctor, cheat, version."""

from __future__ import annotations

import asyncio
import json
import shutil

import typer
from dotenv import load_dotenv

from tb.lib.db import async_connect
from tb.lib.queries.platform import fetch_platform_summary
from tb.lib.systemd import list_timers

load_dotenv()

app = typer.Typer(no_args_is_help=True, help="CLI meta commands")

CHEAT_SHEET = """
tb status / tb prelive / tb meta doctor
tb trask status / tb trask dashboard --once
tb workers list / tb workers run <name> [--dry-run] [--date]
tb universe sync --tier eod|intraday [--apply]
tb canonical status / tb intraday coverage
tb now price AAPL / tb now indicators AAPL
tb logs <svc> / tb restart <svc> / tb deploy --all
tb db ping / tb db shell / tb db migrate [--prod]
tb secrets decrypt dev / tb secrets edit dev
"""


@app.command("doctor")
def meta_doctor(json_output: bool = typer.Option(False, "--json")) -> None:
    """Run quick health checks: DB, disk, timers, platform summary."""
    checks: list[dict[str, str]] = []

    async def _db() -> dict[str, object]:
        async with async_connect() as conn:
            ok = await conn.fetchval("SELECT 1")
            summary = await fetch_platform_summary(conn)
        return {"ok": ok == 1, **summary}

    try:
        summary = asyncio.run(_db())
        checks.append({"name": "database", "status": "PASS", "detail": "connected"})
        checks.append(
            {
                "name": "eod_universe",
                "status": "PASS",
                "detail": str(summary["active_eod_universe"]),
            },
        )
    except Exception as exc:  # noqa: BLE001
        checks.append({"name": "database", "status": "FAIL", "detail": str(exc)})

    usage = shutil.disk_usage("/")
    free_pct = round(100.0 * usage.free / usage.total, 1)
    disk_status = "PASS" if free_pct >= 20 else "WARN"
    checks.append(
        {"name": "disk", "status": disk_status, "detail": f"{free_pct}% free"}
    )

    timers = list_timers()
    checks.append(
        {
            "name": "systemd_timers",
            "status": "PASS" if "theeye-" in timers else "WARN",
            "detail": "theeye timers present" if "theeye-" in timers else "no timers",
        },
    )

    fails = sum(1 for c in checks if c["status"] == "FAIL")
    if json_output:
        typer.echo(json.dumps({"checks": checks, "fail_count": fails}, indent=2))
    else:
        typer.echo("tb meta doctor")
        for check in checks:
            typer.echo(f"  [{check['status']}] {check['name']}: {check['detail']}")
        typer.echo(f"\nResult: {fails} FAIL" if fails else "\nResult: OK")
    raise typer.Exit(code=1 if fails else 0)


@app.command("cheat")
def meta_cheat() -> None:
    """Print operator cheat sheet."""
    typer.echo(CHEAT_SHEET.strip())


@app.command("version")
def meta_version() -> None:
    """Show tb CLI version."""
    typer.echo("tb 0.2.0 (theeyebeta prod CLI)")
