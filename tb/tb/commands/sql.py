"""``tb sql`` — read-only SQL helpers."""

from __future__ import annotations

import typer

from tb.lib.db import sync_connect

app = typer.Typer(no_args_is_help=True, help="SQL query helpers")


@app.command("query")
def sql_query(
    sql: str = typer.Argument(..., help="SELECT query"),
    limit: int = typer.Option(100, "--limit"),
) -> None:
    """Run a read-only SELECT query."""
    normalized = sql.strip().lower()
    if not normalized.startswith("select") and not normalized.startswith("with"):
        typer.echo("Only SELECT/WITH queries allowed", err=True)
        raise typer.Exit(code=1)
    safe_limit = max(1, min(limit, 10_000))
    with sync_connect() as conn:
        conn.execute("SET default_transaction_read_only = on")
        rows = conn.execute(f"{sql.rstrip(';')} LIMIT {safe_limit}").fetchall()  # noqa: S608
    for row in rows:
        typer.echo(str(dict(row)))


@app.command("explain")
def sql_explain(sql: str = typer.Argument(...)) -> None:
    """EXPLAIN a query plan."""
    with sync_connect() as conn:
        rows = conn.execute(f"EXPLAIN {sql}").fetchall()
    for row in rows:
        typer.echo(row.get("QUERY PLAN", row))
