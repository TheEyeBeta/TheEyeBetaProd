"""Rich console helpers."""

from __future__ import annotations

from rich.console import Console
from rich.table import Table

console = Console()


def print_table(title: str, columns: list[str], rows: list[list[str]]) -> None:
    """Render a simple Rich table."""
    table = Table(title=title, show_header=True)
    for col in columns:
        table.add_column(col)
    for row in rows:
        table.add_row(*row)
    console.print(table)
