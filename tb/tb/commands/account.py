"""``tb account`` — read-only Alpaca cash/equity/buying_power lookup."""

from __future__ import annotations

import os

import httpx
import typer
from dotenv import load_dotenv

load_dotenv()

app = typer.Typer(no_args_is_help=True, help="Alpaca paper-account balance lookup")

DEFAULT_BROKER_ADAPTER_URL = "http://127.0.0.1:7090"
_KNOWN_ACCOUNTS = ("zinc", "nyse", "nasdaq")


def _broker_adapter_url() -> str:
    return os.environ.get("BROKER_ADAPTER_URL", DEFAULT_BROKER_ADAPTER_URL).rstrip("/")


def _print_account(acct: dict[str, object]) -> None:
    typer.echo(
        f"  {acct['account']:<8} cash={acct['cash']:>14,.2f}  "
        f"equity={acct['equity']:>14,.2f}  "
        f"buying_power={acct['buying_power']:>14,.2f}  "
        f"portfolio_value={acct['portfolio_value']:>14,.2f}",
    )


@app.command("balance")
def balance(
    account: str = typer.Option(
        "all",
        "--account",
        "-a",
        help="zinc | nyse | nasdaq | all",
    ),
) -> None:
    """Print cash/equity/buying_power for one or all paper sub-accounts."""
    if account != "all" and account not in _KNOWN_ACCOUNTS:
        raise typer.BadParameter(
            f"--account must be one of {(*_KNOWN_ACCOUNTS, 'all')}"
        )

    base_url = _broker_adapter_url()
    with httpx.Client(timeout=15.0) as client:
        if account == "all":
            response = client.get(f"{base_url}/v1/account/all")
            response.raise_for_status()
            for acct in response.json()["accounts"]:
                _print_account(acct)
        else:
            response = client.get(f"{base_url}/v1/account", params={"account": account})
            response.raise_for_status()
            _print_account(response.json())
