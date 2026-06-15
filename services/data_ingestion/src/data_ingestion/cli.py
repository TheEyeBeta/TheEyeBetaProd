"""CLI entry point: tb-ingest.

Commands
--------
tb-ingest prices --date YYYY-MM-DD           Ingest daily prices (default: today).
tb-ingest macro  --date YYYY-MM-DD           Ingest macro indicators (default: today).
tb-ingest all    --date YYYY-MM-DD           Run prices then macro.
tb-ingest backfill prices --start … --end …  Backfill price history.
tb-ingest backfill macro  --start … --end …  Backfill macro history.
tb-ingest backfill all    --start … --end …  Backfill prices + macro.
"""

from __future__ import annotations

import asyncio
import sys
from datetime import date

import structlog
import typer
from dotenv import load_dotenv

load_dotenv()

log = structlog.get_logger()

app = typer.Typer(
    name="tb-ingest",
    help="theeyebeta data ingestion CLI",
    no_args_is_help=True,
)

backfill_app = typer.Typer(
    help="Backfill historical data over an explicit date range.",
    no_args_is_help=True,
)
app.add_typer(backfill_app, name="backfill")


def _parse_date(date_str: str | None) -> date:
    """Parse a date string or return today.

    Args:
        date_str: ISO-format date string, or None.

    Returns:
        Parsed date, defaulting to today.
    """
    if date_str is None:
        return date.today()
    try:
        return date.fromisoformat(date_str)
    except ValueError:
        typer.echo(f"Invalid date: {date_str!r}. Expected YYYY-MM-DD.", err=True)
        raise typer.Exit(code=1) from None


@app.command()
def prices(
    date_str: str | None = typer.Option(
        None,
        "--date",
        help="Target date YYYY-MM-DD (default: today)",
        show_default=True,
    ),
) -> None:
    """Ingest daily OHLCV prices for all active instruments."""
    from data_ingestion.pipeline import ingest_prices  # noqa: PLC0415

    target = _parse_date(date_str)
    typer.echo(f"Ingesting prices for {target} …")
    try:
        result = asyncio.run(ingest_prices(target))
    except Exception as exc:  # noqa: BLE001
        log.error("prices_failed", error=str(exc))
        typer.echo(f"FAILED: {exc}", err=True)
        raise typer.Exit(code=1) from None

    typer.echo(
        f"prices done — date={result['date']} requested={result['requested']} "
        f"written={result['written']} skipped={result['skipped']}"
    )


@app.command()
def macro(
    date_str: str | None = typer.Option(
        None,
        "--date",
        help="End date YYYY-MM-DD (default: today); lookback is 30 days",
        show_default=True,
    ),
) -> None:
    """Ingest macro indicator observations (30-day lookback)."""
    from data_ingestion.pipeline import ingest_macro  # noqa: PLC0415

    target = _parse_date(date_str)
    typer.echo(f"Ingesting macro indicators up to {target} …")
    try:
        result = asyncio.run(ingest_macro(target))
    except Exception as exc:  # noqa: BLE001
        log.error("macro_failed", error=str(exc))
        typer.echo(f"FAILED: {exc}", err=True)
        raise typer.Exit(code=1) from None

    typer.echo(
        f"macro done — series={result['series']} "
        f"points_written={result['points_written']}"
    )


@app.command(name="all")
def all_ingest(
    date_str: str | None = typer.Option(
        None,
        "--date",
        help="Target date YYYY-MM-DD (default: today)",
        show_default=True,
    ),
) -> None:
    """Run prices ingestion followed by macro ingestion."""
    from data_ingestion.pipeline import ingest_macro, ingest_prices  # noqa: PLC0415

    target = _parse_date(date_str)
    typer.echo(f"Running full ingest for {target} …")

    failed = False

    try:
        price_result = asyncio.run(ingest_prices(target))
        typer.echo(
            f"  prices — requested={price_result['requested']} "
            f"written={price_result['written']} skipped={price_result['skipped']}"
        )
    except Exception as exc:  # noqa: BLE001
        log.error("prices_failed", error=str(exc))
        typer.echo(f"  prices FAILED: {exc}", err=True)
        failed = True

    try:
        macro_result = asyncio.run(ingest_macro(target))
        typer.echo(
            f"  macro  — series={macro_result['series']} "
            f"points_written={macro_result['points_written']}"
        )
    except Exception as exc:  # noqa: BLE001
        log.error("macro_failed", error=str(exc))
        typer.echo(f"  macro FAILED: {exc}", err=True)
        failed = True

    if failed:
        sys.exit(1)

    typer.echo("All done.")


# ── Backfill commands ─────────────────────────────────────────────────────────

def _default_start() -> date:
    """Return a date 5 years before today."""
    today = date.today()
    return date(today.year - 5, today.month, today.day)


@backfill_app.command(name="prices")
def backfill_prices(
    start_str: str | None = typer.Option(
        None,
        "--start",
        help="Start date YYYY-MM-DD (default: 5 years ago)",
    ),
    end_str: str | None = typer.Option(
        None,
        "--end",
        help="End date YYYY-MM-DD (default: today)",
    ),
) -> None:
    """Backfill daily OHLCV prices for all active instruments over a date range."""
    from data_ingestion.pipeline import backfill_prices as _run  # noqa: PLC0415

    start = date.fromisoformat(start_str) if start_str else _default_start()
    end = date.fromisoformat(end_str) if end_str else date.today()
    typer.echo(f"Backfilling prices {start} → {end} …")
    try:
        result = asyncio.run(_run(start, end))
    except Exception as exc:  # noqa: BLE001
        log.error("backfill_prices_failed", error=str(exc))
        typer.echo(f"FAILED: {exc}", err=True)
        raise typer.Exit(code=1) from None

    typer.echo(
        f"backfill prices done — instruments={result['requested']} "
        f"written={result['written']}"
    )


@backfill_app.command(name="macro")
def backfill_macro(
    start_str: str | None = typer.Option(
        None,
        "--start",
        help="Start date YYYY-MM-DD (default: 5 years ago)",
    ),
    end_str: str | None = typer.Option(
        None,
        "--end",
        help="End date YYYY-MM-DD (default: today)",
    ),
) -> None:
    """Backfill macro indicator observations over a date range."""
    from data_ingestion.pipeline import backfill_macro as _run  # noqa: PLC0415

    start = date.fromisoformat(start_str) if start_str else _default_start()
    end = date.fromisoformat(end_str) if end_str else date.today()
    typer.echo(f"Backfilling macro {start} → {end} …")
    try:
        result = asyncio.run(_run(start, end))
    except Exception as exc:  # noqa: BLE001
        log.error("backfill_macro_failed", error=str(exc))
        typer.echo(f"FAILED: {exc}", err=True)
        raise typer.Exit(code=1) from None

    typer.echo(
        f"backfill macro done — series={result['series']} "
        f"points_written={result['points_written']}"
    )


@backfill_app.command(name="all")
def backfill_all(
    start_str: str | None = typer.Option(
        None,
        "--start",
        help="Start date YYYY-MM-DD (default: 5 years ago)",
    ),
    end_str: str | None = typer.Option(
        None,
        "--end",
        help="End date YYYY-MM-DD (default: today)",
    ),
) -> None:
    """Backfill prices and macro indicators over a date range."""
    from data_ingestion.pipeline import backfill_macro as _bmacro  # noqa: PLC0415
    from data_ingestion.pipeline import backfill_prices as _bprices  # noqa: PLC0415

    start = date.fromisoformat(start_str) if start_str else _default_start()
    end = date.fromisoformat(end_str) if end_str else date.today()
    typer.echo(f"Backfilling all data {start} → {end} …")

    failed = False

    try:
        pr = asyncio.run(_bprices(start, end))
        typer.echo(
            f"  prices — instruments={pr['requested']} written={pr['written']}"
        )
    except Exception as exc:  # noqa: BLE001
        log.error("backfill_prices_failed", error=str(exc))
        typer.echo(f"  prices FAILED: {exc}", err=True)
        failed = True

    try:
        mr = asyncio.run(_bmacro(start, end))
        typer.echo(
            f"  macro  — series={mr['series']} points_written={mr['points_written']}"
        )
    except Exception as exc:  # noqa: BLE001
        log.error("backfill_macro_failed", error=str(exc))
        typer.echo(f"  macro FAILED: {exc}", err=True)
        failed = True

    if failed:
        sys.exit(1)

    typer.echo("Backfill complete.")
