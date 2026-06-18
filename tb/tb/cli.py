"""Root Typer application for the ``tb`` CLI."""

from __future__ import annotations

import typer

from tb.commands.account import app as account_app
from tb.commands.backtest import app as backtest_app
from tb.commands.canonical import app as canonical_app
from tb.commands.config import app as config_app
from tb.commands.db import app as db_app
from tb.commands.deploy import deploy_app
from tb.commands.engine import app as engine_app
from tb.commands.export import app as export_app
from tb.commands.fundamentals import app as fundamentals_app
from tb.commands.indicators import app as indicators_app
from tb.commands.instrument import app as instrument_app
from tb.commands.intraday import app as intraday_app
from tb.commands.meta import app as meta_app
from tb.commands.now import app as now_app
from tb.commands.ops import logs_service, restart_service
from tb.commands.pipeline import app as pipeline_app
from tb.commands.plot import app as plot_app
from tb.commands.prelive import app as prelive_app
from tb.commands.prices import app as prices_app
from tb.commands.quant import app as quant_app
from tb.commands.returns import app as returns_app
from tb.commands.secrets import app as secrets_app
from tb.commands.signals import app as signals_app
from tb.commands.snapshot import app as snapshot_app
from tb.commands.snapshots import app as snapshots_app
from tb.commands.sql import app as sql_app
from tb.commands.status_cmd import app as status_app
from tb.commands.strategies import app as strategies_app
from tb.commands.trask import app as trask_app
from tb.commands.universe import app as universe_app
from tb.commands.workers import app as workers_app

app = typer.Typer(no_args_is_help=True, help="theeyebeta management CLI")

# Data platform
app.add_typer(status_app, name="status")
app.add_typer(prelive_app, name="prelive")
app.add_typer(now_app, name="now")
app.add_typer(engine_app, name="engine")
app.add_typer(canonical_app, name="canonical")
app.add_typer(intraday_app, name="intraday")
app.add_typer(trask_app, name="trask")
app.add_typer(workers_app, name="workers")
app.add_typer(pipeline_app, name="pipeline")
app.add_typer(universe_app, name="universe")
app.add_typer(instrument_app, name="instrument")
app.add_typer(snapshots_app, name="snapshots")

# Data engine
app.add_typer(prices_app, name="prices")
app.add_typer(indicators_app, name="indicators")
app.add_typer(returns_app, name="returns")
app.add_typer(snapshot_app, name="snapshot")
app.add_typer(export_app, name="export")
app.add_typer(fundamentals_app, name="fundamentals")
app.add_typer(plot_app, name="plot")
app.add_typer(quant_app, name="quant")

# Research
app.add_typer(backtest_app, name="backtest")
app.add_typer(strategies_app, name="strategies")
app.add_typer(signals_app, name="signals")
app.add_typer(sql_app, name="sql")

# Trading
app.add_typer(account_app, name="account")

# Infra
app.add_typer(db_app, name="db")
app.add_typer(secrets_app, name="secrets")
app.add_typer(deploy_app, name="deploy")
app.add_typer(config_app, name="config")
app.add_typer(meta_app, name="meta")


@app.command("logs")
def logs_top(
    service: str = typer.Argument(..., help="Docker service or worker alias"),
    tail: int = typer.Option(100, "--tail", "-n"),
    follow: bool = typer.Option(False, "--follow", "-f"),
) -> None:
    """Tail logs for a Docker service or theeye worker."""
    logs_service(service, tail=tail, follow=follow)


@app.command("restart")
def restart_top(
    service: str = typer.Argument(..., help="Docker compose service name"),
    yes: bool = typer.Option(False, "--yes", "-y"),
) -> None:
    """Restart one Docker Compose service."""
    restart_service(service, yes=yes)
