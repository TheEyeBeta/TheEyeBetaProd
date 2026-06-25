"""``tb workers`` — run ingestion workers."""

from __future__ import annotations

import subprocess

import typer

from tb.lib.paths import REPO_ROOT
from tb.lib.systemd import journal_tail, list_timers

app = typer.Typer(no_args_is_help=True, help="Run canonical workers")

WORKER_MODULES: dict[str, str] = {
    "macro-ingest": "workers.macro_ingestion_worker",
    "macro-regime": "workers.macro_regime_worker",
    "massive-ingest": "workers.massive_ingestion_worker",
    "intraday-ingest": "workers.intraday_ingestion_worker",
    "indicator-compute": "workers.indicator_compute_worker",
    "indicator-validate": "workers.theeyebeta_indicator_worker",
    "daily-pipeline": "workers.daily_pipeline_runner",
    "gap-sentinel": "workers.gap_sentinel_worker",
    "sector": "workers.sector_aggregation_worker",
    "market-cap-fetch": "workers.market_cap_fetch_worker",
    "market-cap-threshold": "workers.market_cap_threshold_worker",
    "supabase-sync": "workers.supabase_sync_worker",
}

# Standalone scripts (not `-m` modules)
SCRIPT_WORKERS: dict[str, str] = {
    "news-ingest": "scripts/run_news_ingest.py",
    "news-bridge": "scripts/sync_market_news.py",
}

WORKER_UNITS: dict[str, str] = {
    "macro-ingest": "theeye-macro.service",
    "massive-ingest": "theeye-massive-ingest.service",
    "intraday-ingest": "theeye-intraday-ingest.service",
    "daily-pipeline": "theeye-daily-pipeline.service",
    "gap-sentinel": "theeye-gap-sentinel.service",
    "sector": "theeye-sector.service",
    "market-cap-fetch": "theeye-market-cap.service",
    "news-ingest": "theeye-news-ingest.service",
    "news-bridge": "theeye-news-bridge.service",
}


@app.command("list")
def workers_list() -> None:
    """List runnable worker aliases."""
    for alias, module in sorted(WORKER_MODULES.items()):
        typer.echo(f"{alias:24} -> {module}")
    for alias, script in sorted(SCRIPT_WORKERS.items()):
        typer.echo(f"{alias:24} -> {script}")


@app.command("run")
def workers_run(
    name: str = typer.Argument(..., help="Worker alias from `tb workers list`"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Plan only, no writes"),
    date: str | None = typer.Option(None, "--date", help="Trade date YYYY-MM-DD"),
    force: bool = typer.Option(False, "--force", help="Pass --force when supported"),
) -> None:
    """Run one worker module via uv."""
    if name in SCRIPT_WORKERS:
        script = SCRIPT_WORKERS[name]
        cmd = ["uv", "run", "python", script]
        typer.echo(" ".join(cmd))
        proc = subprocess.run(cmd, cwd=REPO_ROOT, check=False)  # noqa: S603
        raise typer.Exit(code=proc.returncode)

    module = WORKER_MODULES.get(name)
    if module is None and name not in SCRIPT_WORKERS:
        typer.echo(f"Unknown worker {name!r}. Run `tb workers list`.", err=True)
        raise typer.Exit(code=1)
    cmd = ["uv", "run", "python", "-m", module, "--run-type", "manual"]
    if dry_run:
        cmd.append("--dry-run")
    if date:
        cmd.extend(["--date", date])
    if force:
        cmd.append("--force")
    typer.echo(" ".join(cmd))
    proc = subprocess.run(cmd, cwd=REPO_ROOT, check=False)  # noqa: S603
    raise typer.Exit(code=proc.returncode)


@app.command("tail")
def workers_tail(
    name: str = typer.Argument(..., help="Worker alias"),
    lines: int = typer.Option(100, "--lines", "-n"),
    follow: bool = typer.Option(False, "--follow", "-f"),
) -> None:
    """Tail systemd journal for a worker unit."""
    unit = WORKER_UNITS.get(name)
    if not unit:
        typer.echo(f"No systemd unit mapped for {name!r}", err=True)
        raise typer.Exit(code=1)
    raise typer.Exit(journal_tail(unit, lines=lines, follow=follow))


@app.command("schedule")
def workers_schedule() -> None:
    """List theeye systemd timers."""
    typer.echo(list_timers())
