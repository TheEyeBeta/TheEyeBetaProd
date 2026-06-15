"""``tb secrets`` — sops wrapper."""

from __future__ import annotations

import subprocess

import typer

from tb.lib.paths import REPO_ROOT, SECRETS_DIR

app = typer.Typer(no_args_is_help=True, help="Decrypt or edit sops secrets")


@app.command("decrypt")
def secrets_decrypt(
    env: str = typer.Argument("dev", help="Environment: dev, prod, staging"),
) -> None:
    """Decrypt secrets/<env>.enc.yaml to .env."""
    script = REPO_ROOT / "scripts" / "decrypt-env.sh"
    proc = subprocess.run(["bash", str(script), env], cwd=REPO_ROOT, check=False)  # noqa: S603, S607
    raise typer.Exit(code=proc.returncode)


@app.command("edit")
def secrets_edit(
    env: str = typer.Argument("dev", help="Environment: dev, prod, staging"),
) -> None:
    """Open secrets file in sops editor."""
    enc = SECRETS_DIR / f"{env}.enc.yaml"
    if not enc.is_file():
        typer.echo(f"Missing {enc}", err=True)
        raise typer.Exit(code=1)
    proc = subprocess.run(["sops", str(enc)], cwd=REPO_ROOT, check=False)  # noqa: S603, S607
    raise typer.Exit(code=proc.returncode)
