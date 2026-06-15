"""``tb deploy`` — Docker Compose deploy."""

from __future__ import annotations

import typer

from tb.lib.compose import compose_deploy

deploy_app = typer.Typer(no_args_is_help=True, help="Deploy Docker services")


@deploy_app.callback(invoke_without_command=True)
def deploy(
    ctx: typer.Context,
    service: str | None = typer.Argument(None, help="Service name (omit with --all)"),
    all_services: bool = typer.Option(False, "--all", help="Deploy all services"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
) -> None:
    """Pull images and restart service(s)."""
    if ctx.invoked_subcommand is not None:
        return
    target = "all services" if all_services else (service or "")
    if not all_services and not service:
        typer.echo("Specify a service name or --all", err=True)
        raise typer.Exit(code=1)
    if not yes:
        typer.echo(f"Deploy {target} on this host?")
        if not typer.confirm("Continue?", default=False):
            typer.echo("Aborted.")
            raise typer.Exit(code=1)
    code = compose_deploy(None if all_services else service)
    raise typer.Exit(code=code)
