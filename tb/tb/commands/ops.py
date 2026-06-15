"""Top-level log/restart helpers."""

from __future__ import annotations

import typer

from tb.lib.compose import compose_logs, compose_restart
from tb.lib.systemd import journal_tail

WORKER_UNITS: dict[str, str] = {
    "macro-ingest": "theeye-macro.service",
    "massive-ingest": "theeye-massive-ingest.service",
    "intraday-ingest": "theeye-intraday-ingest.service",
    "daily-pipeline": "theeye-daily-pipeline.service",
    "gap-sentinel": "theeye-gap-sentinel.service",
    "sector": "theeye-sector.service",
    "market-cap": "theeye-market-cap.service",
}


def logs_service(
    service: str,
    *,
    tail: int = 100,
    follow: bool = False,
) -> None:
    """Tail Docker or systemd logs."""
    unit = WORKER_UNITS.get(service)
    if unit:
        raise typer.Exit(journal_tail(unit, lines=tail, follow=follow))
    raise typer.Exit(compose_logs(service, tail=tail, follow=follow))


def restart_service(service: str, *, yes: bool = False) -> None:
    """Restart a Docker Compose service."""
    if not yes:
        typer.echo(f"Restart {service} on this host?")
        if not typer.confirm("Continue?", default=False):
            typer.echo("Aborted.")
            raise typer.Exit(code=1)
    raise typer.Exit(compose_restart(service))
