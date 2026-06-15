"""``tb config`` — configuration inspection."""

from __future__ import annotations

import os

import typer

app = typer.Typer(no_args_is_help=True, help="Configuration helpers")

REQUIRED_ENV = (
    "DATABASE_URL",
    "INGEST_DATABASE_URL",
    "MASSIVE_API_KEY",
)


@app.command("show")
def config_show(
    mask_secrets: bool = typer.Option(True, "--mask-secrets/--no-mask"),
) -> None:
    """Show resolved environment keys (names only for secrets)."""
    for key in sorted(os.environ):
        if key.startswith(("_", "LS_", "SHLVL")):
            continue
        val = os.environ[key]
        if mask_secrets and any(
            s in key.upper() for s in ("KEY", "SECRET", "PASSWORD", "TOKEN")
        ):
            val = "***"
        typer.echo(f"{key}={val}")


@app.command("validate")
def config_validate() -> None:
    """Validate required environment variables."""
    missing = [k for k in REQUIRED_ENV if not os.environ.get(k)]
    if missing:
        typer.echo(f"Missing: {', '.join(missing)}", err=True)
        raise typer.Exit(code=1)
    typer.echo("Required env vars present.")


env_app = typer.Typer(help="Environment checks")
app.add_typer(env_app, name="env")


@env_app.command("check")
def config_env_check() -> None:
    """Check required env vars."""
    config_validate()
