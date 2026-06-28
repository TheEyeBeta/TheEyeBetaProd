"""Plotting commands for stock charts with indicators.

Subcommands:
    all      - Price + all SMA/EMA overlays
    ema      - Price + EMA (10, 50, 200)
    sma      - Price + SMA (10, 50, 200)
    price    - Price only
    volume   - Price + volume bars
    rsi      - Price + RSI(14) subplot
    macd     - Price + MACD/signal/histogram subplot
    splits   - Price with corporate-action markers
    full     - Comprehensive multi-panel chart (price, volume, RSI, MACD, splits)
    custom   - Pick any combination of overlays
"""

from __future__ import annotations

import os

import typer
from rich.console import Console

console = Console()

plot_app = typer.Typer(name="plot", help="Plot stock charts with indicators")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _is_interactive() -> bool:
    """Check if we're in an interactive GUI environment."""
    has_display = (
        os.getenv("DISPLAY") is not None or os.getenv("WAYLAND_DISPLAY") is not None
    )
    try:
        import sys

        is_tty = sys.stdout.isatty()
    except Exception:
        is_tty = False
    try:
        import matplotlib

        backend = matplotlib.get_backend().lower()
        if backend in ("agg", "pdf", "svg", "ps"):
            return False
    except Exception:
        pass
    return has_display and is_tty


def _get_chart_data(ticker: str, range: str = "2y"):
    """Get chart bundle data from theeyebeta schema."""
    from tb.lib.plot.chart_data import RangeLiteral, load_chart_bundle

    range_key: RangeLiteral = range if range in ("1y", "2y", "5y") else "2y"  # type: ignore[assignment]
    try:
        return load_chart_bundle(ticker, range_key)
    except ValueError as exc:
        console.print(f"[red]Error: {exc}[/red]")
        raise typer.Exit(1) from exc


def _setup_matplotlib():
    """Import and configure matplotlib. Returns (matplotlib, plt, mdates, datetime)."""
    try:
        import matplotlib

        is_gui_available = _is_interactive()
        if not is_gui_available:
            matplotlib.use("Agg")
        else:
            for backend in ("TkAgg", "Qt5Agg", "Qt4Agg", "GTK3Agg", "GTK4Agg"):
                try:
                    matplotlib.use(backend)
                    break
                except Exception:
                    continue
            else:
                console.print(
                    "[yellow]Warning: No GUI backend available. "
                    "Install python3-tk for interactive plots.[/yellow]"
                )
                matplotlib.use("Agg")

        from datetime import datetime

        import matplotlib.dates as mdates
        import matplotlib.pyplot as plt

        # Modern style
        for style_name in ("seaborn-v0_8-darkgrid", "seaborn-darkgrid", "default"):
            try:
                plt.style.use(style_name)
                break
            except Exception:
                continue

        return matplotlib, plt, mdates, datetime
    except ImportError as exc:
        console.print(
            "[red]Error: matplotlib is required. Install with: pip install matplotlib[/red]"
        )
        raise typer.Exit(1) from exc


# Professional color palette
COLORS = {
    "price": "#1F2937",
    "sma_10": "#3B82F6",
    "sma_50": "#10B981",
    "sma_200": "#EF4444",
    "ema_10": "#06B6D4",
    "ema_50": "#F59E0B",
    "ema_200": "#8B5CF6",
    "ema_12": "#10B981",  # Green (fast MACD component)
    "ema_26": "#EF4444",  # Red (slow MACD component)
    "volume_up": "#10B981",
    "volume_down": "#EF4444",
    "rsi": "#8B5CF6",
    "rsi_zone": "#E5E7EB",
    "macd_line": "#3B82F6",
    "macd_signal": "#EF4444",
    "macd_hist_pos": "#10B981",
    "macd_hist_neg": "#EF4444",
    "split": "#F59E0B",
    "dividend": "#06B6D4",
    "golden_cross": "#10B981",
    "death_cross": "#EF4444",
}


def _save_or_show(matplotlib, plt, ticker: str, range: str, save_path: str | None):
    """Handle save/show logic for all chart types."""
    current_backend = matplotlib.get_backend().lower()
    has_display = (
        os.getenv("DISPLAY") is not None or os.getenv("WAYLAND_DISPLAY") is not None
    )
    is_gui = current_backend != "agg" and has_display

    if save_path:
        plt.savefig(save_path, dpi=150, bbox_inches="tight")
        console.print(f"[green]Chart saved to: {save_path}[/green]")
        if is_gui:
            plt.show(block=True)
    elif is_gui:
        console.print("[green]Displaying chart in window...[/green]")
        plt.show(block=True)
    else:
        default_path = f"{ticker.lower()}_chart_{range}.png"
        plt.savefig(default_path, dpi=150, bbox_inches="tight")
        console.print(f"[green]Chart saved to: {default_path}[/green]")
        if has_display and current_backend == "agg":
            console.print(
                "[yellow]Note: Install python3-tk for interactive plots.[/yellow]"
            )
        else:
            console.print(
                "[dim]Running in non-interactive mode. Use --save for custom filename.[/dim]"
            )

    plt.close()


def _style_axis(ax, title: str, ylabel: str):
    """Apply consistent modern styling to an axis."""
    ax.set_facecolor("#FAFAFA")
    ax.set_title(title, fontsize=16, fontweight="bold", pad=10, color="#111827")
    ax.set_ylabel(ylabel, fontsize=11, fontweight="500", color="#374151", labelpad=8)
    ax.grid(True, alpha=0.25, linestyle="-", linewidth=0.5, color="#9CA3AF", zorder=0)
    ax.set_axisbelow(True)
    for spine in ax.spines.values():
        spine.set_color("#D1D5DB")
        spine.set_linewidth(0.8)


def _plot_price_on_ax(ax, dates, bundle, overlays: dict[str, bool]):
    """Draw price and optional SMA/EMA overlays on the given axis."""
    # Price
    close = bundle.prices["close"]
    px_data = [p for p in close if p is not None]
    px_dates = [d for d, p in zip(dates, close) if p is not None]
    if px_data:
        ax.plot(
            px_dates,
            px_data,
            label="Price",
            color=COLORS["price"],
            linewidth=2.5,
            zorder=10,
            alpha=0.95,
        )

    # SMA overlays (solid)
    for key, label, width in [
        ("sma_10", "SMA 10", 2),
        ("sma_50", "SMA 50", 2),
        ("sma_200", "SMA 200", 2.2),
    ]:
        if overlays.get(key):
            vals = bundle.indicators.get(key, [])
            d_v = [(d, v) for d, v in zip(dates, vals) if v is not None]
            if d_v:
                ax.plot(
                    [x[0] for x in d_v],
                    [x[1] for x in d_v],
                    label=label,
                    color=COLORS[key],
                    linewidth=width,
                    alpha=0.85,
                    zorder=5,
                )

    # EMA overlays (dashed)
    for key, label, width, dash in [
        ("ema_10", "EMA 10", 2, (8, 4)),
        ("ema_50", "EMA 50", 2, (8, 4)),
        ("ema_200", "EMA 200", 2.2, (10, 5)),
        ("ema_12", "EMA 12", 1.8, (6, 3)),  # Fast MACD component
        ("ema_26", "EMA 26", 1.8, (6, 3)),  # Slow MACD component
    ]:
        if overlays.get(key):
            vals = bundle.indicators.get(key, [])
            d_v = [(d, v) for d, v in zip(dates, vals) if v is not None]
            if d_v:
                ax.plot(
                    [x[0] for x in d_v],
                    [x[1] for x in d_v],
                    label=label,
                    color=COLORS[key],
                    linewidth=width,
                    linestyle="--",
                    alpha=0.8,
                    zorder=4,
                    dashes=dash,
                )

    # Golden / Death cross markers
    if overlays.get("crosses"):
        gc = bundle.indicators.get("golden_cross_sma", [])
        dc = bundle.indicators.get("death_cross_sma", [])
        for i, d in enumerate(dates):
            if i < len(close) and close[i] is not None:
                if i < len(gc) and gc[i]:
                    ax.annotate(
                        "★",
                        xy=(d, close[i]),
                        fontsize=14,
                        color=COLORS["golden_cross"],
                        ha="center",
                        va="bottom",
                        zorder=15,
                    )
                if i < len(dc) and dc[i]:
                    ax.annotate(
                        "✖",
                        xy=(d, close[i]),
                        fontsize=12,
                        color=COLORS["death_cross"],
                        ha="center",
                        va="top",
                        zorder=15,
                    )


def _plot_corporate_actions_on_ax(ax, dates, bundle):
    """Draw vertical lines / annotations for splits and dividends."""
    from datetime import datetime as dt

    if not bundle.corporate_actions:
        return

    y_min, y_max = ax.get_ylim()

    for ca in bundle.corporate_actions:
        try:
            ca_date = dt.fromisoformat(ca.action_date)
        except Exception:
            continue

        if ca.action_type == "SPLIT" and ca.split_ratio:
            ax.axvline(
                ca_date,
                color=COLORS["split"],
                linestyle="--",
                linewidth=1.2,
                alpha=0.7,
                zorder=3,
            )
            ax.annotate(
                f"Split {ca.split_ratio}:1",
                xy=(ca_date, y_max),
                xytext=(0, 5),
                textcoords="offset points",
                fontsize=8,
                fontweight="bold",
                color=COLORS["split"],
                ha="center",
                va="bottom",
                rotation=90,
                bbox=dict(
                    boxstyle="round,pad=0.2", fc="white", ec=COLORS["split"], alpha=0.9
                ),
            )
        elif ca.action_type == "DIVIDEND" and ca.dividend_amount:
            ax.axvline(
                ca_date,
                color=COLORS["dividend"],
                linestyle=":",
                linewidth=0.8,
                alpha=0.5,
                zorder=2,
            )


def _format_xaxis(ax, mdates, plt):
    """Apply consistent x-axis date formatting."""
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %Y"))
    ax.xaxis.set_major_locator(mdates.MonthLocator(interval=2))
    ax.xaxis.set_minor_locator(mdates.MonthLocator())
    plt.setp(ax.xaxis.get_majorticklabels(), rotation=45, ha="right", fontsize=10)


# ---------------------------------------------------------------------------
# Core plotting functions
# ---------------------------------------------------------------------------


def _plot_chart(
    ticker: str,
    show_price: bool = False,
    show_sma_10: bool = False,
    show_sma_50: bool = False,
    show_sma_200: bool = False,
    show_ema_10: bool = False,
    show_ema_50: bool = False,
    show_ema_200: bool = False,
    show_ema_12: bool = False,
    show_ema_26: bool = False,
    show_volume: bool = False,
    show_rsi: bool = False,
    show_macd: bool = False,
    show_splits: bool = False,
    show_crosses: bool = False,
    range: str = "2y",
    save_path: str | None = None,
):
    """Plot chart with specified indicators and optional subplots."""
    matplotlib, plt, mdates, datetime = _setup_matplotlib()

    bundle = _get_chart_data(ticker, range)
    dates = [datetime.fromisoformat(d) for d in bundle.dates]

    # Determine layout: count subplots needed
    extra_panels = []
    if show_volume:
        extra_panels.append("volume")
    if show_rsi:
        extra_panels.append("rsi")
    if show_macd:
        extra_panels.append("macd")

    n_panels = 1 + len(extra_panels)
    height_ratios = [3] + [1] * len(extra_panels)

    fig, axes = plt.subplots(
        n_panels,
        1,
        figsize=(16, 5 + 3 * len(extra_panels)),
        facecolor="white",
        sharex=True,
        gridspec_kw={"height_ratios": height_ratios, "hspace": 0.12},
        squeeze=False,
    )
    axes = [row[0] for row in axes]  # flatten

    # --- Main price panel ---
    ax_price = axes[0]
    overlays = {
        "sma_10": show_sma_10,
        "sma_50": show_sma_50,
        "sma_200": show_sma_200,
        "ema_10": show_ema_10,
        "ema_50": show_ema_50,
        "ema_200": show_ema_200,
        "ema_12": show_ema_12,
        "ema_26": show_ema_26,
        "crosses": show_crosses,
    }
    if show_price:
        _plot_price_on_ax(ax_price, dates, bundle, overlays)

    if show_splits:
        _plot_corporate_actions_on_ax(ax_price, dates, bundle)

    _style_axis(ax_price, f"{ticker.upper()} Stock Price Chart", "Price ($)")
    ax_price.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, p: f"${x:,.0f}"))
    legend = ax_price.legend(
        loc="upper left",
        fontsize=10,
        framealpha=0.95,
        facecolor="white",
        edgecolor="#E5E7EB",
        frameon=True,
        fancybox=True,
        shadow=False,
        borderpad=0.8,
        labelspacing=0.6,
    )
    legend.get_frame().set_linewidth(0.5)

    # --- Extra panels ---
    panel_idx = 1
    for panel_name in extra_panels:
        ax = axes[panel_idx]
        ax.set_facecolor("#FAFAFA")

        if panel_name == "volume":
            vol = bundle.volume
            close = bundle.prices["close"]
            for i, (d, v) in enumerate(zip(dates, vol)):
                if v is not None and v > 0:
                    prev_close = (
                        close[i - 1] if i > 0 and close[i - 1] is not None else None
                    )
                    cur_close = close[i]
                    if prev_close is not None and cur_close is not None:
                        color = (
                            COLORS["volume_up"]
                            if cur_close >= prev_close
                            else COLORS["volume_down"]
                        )
                    else:
                        color = COLORS["volume_up"]
                    ax.bar(d, v, color=color, alpha=0.6, width=0.8, zorder=3)
            _style_axis(ax, "", "Volume")
            ax.yaxis.set_major_formatter(
                plt.FuncFormatter(
                    lambda x, p: (
                        f"{x / 1e6:.0f}M"
                        if x >= 1e6
                        else f"{x / 1e3:.0f}K"
                        if x >= 1e3
                        else f"{x:.0f}"
                    )
                )
            )

        elif panel_name == "rsi":
            rsi_vals = bundle.indicators.get("rsi_14", [])
            d_v = [(d, v) for d, v in zip(dates, rsi_vals) if v is not None]
            if d_v:
                rsi_dates = [x[0] for x in d_v]
                rsi_data = [x[1] for x in d_v]
                ax.plot(
                    rsi_dates, rsi_data, color=COLORS["rsi"], linewidth=1.5, zorder=5
                )
                ax.axhspan(0, 30, color="#DCFCE7", alpha=0.3, zorder=1)  # oversold zone
                ax.axhspan(
                    70, 100, color="#FEE2E2", alpha=0.3, zorder=1
                )  # overbought zone
                ax.axhline(
                    30, color="#10B981", linestyle="--", linewidth=0.8, alpha=0.6
                )
                ax.axhline(
                    70, color="#EF4444", linestyle="--", linewidth=0.8, alpha=0.6
                )
                ax.axhline(50, color="#9CA3AF", linestyle="-", linewidth=0.5, alpha=0.4)
                ax.set_ylim(0, 100)
            _style_axis(ax, "", "RSI(14)")

        elif panel_name == "macd":
            macd_vals = bundle.indicators.get("macd", [])
            sig_vals = bundle.indicators.get("macd_signal", [])
            hist_vals = bundle.indicators.get("macd_hist", [])

            # MACD line
            d_m = [(d, v) for d, v in zip(dates, macd_vals) if v is not None]
            if d_m:
                ax.plot(
                    [x[0] for x in d_m],
                    [x[1] for x in d_m],
                    color=COLORS["macd_line"],
                    linewidth=1.5,
                    label="MACD",
                    zorder=5,
                )

            # Signal line
            d_s = [(d, v) for d, v in zip(dates, sig_vals) if v is not None]
            if d_s:
                ax.plot(
                    [x[0] for x in d_s],
                    [x[1] for x in d_s],
                    color=COLORS["macd_signal"],
                    linewidth=1.2,
                    label="Signal",
                    zorder=4,
                )

            # Histogram bars
            for d, h in zip(dates, hist_vals):
                if h is not None:
                    color = (
                        COLORS["macd_hist_pos"] if h >= 0 else COLORS["macd_hist_neg"]
                    )
                    ax.bar(d, h, color=color, alpha=0.4, width=0.8, zorder=3)

            ax.axhline(0, color="#9CA3AF", linewidth=0.5, zorder=2)
            ax.legend(loc="upper left", fontsize=8, framealpha=0.9, edgecolor="#E5E7EB")
            _style_axis(ax, "", "MACD")

        ax.grid(
            True, alpha=0.25, linestyle="-", linewidth=0.5, color="#9CA3AF", zorder=0
        )
        ax.set_axisbelow(True)
        for spine in ax.spines.values():
            spine.set_color("#D1D5DB")
            spine.set_linewidth(0.8)
        panel_idx += 1

    # Format x-axis on the bottom panel
    _format_xaxis(axes[-1], mdates, plt)
    axes[-1].set_xlabel(
        "Date", fontsize=11, fontweight="500", color="#374151", labelpad=8
    )
    plt.setp(axes[-1].yaxis.get_majorticklabels(), fontsize=10)

    plt.tight_layout(pad=1.5)
    _save_or_show(matplotlib, plt, ticker, range, save_path)


# ---------------------------------------------------------------------------
# CLI Commands
# ---------------------------------------------------------------------------


@plot_app.command("all")
def plot_all(
    ticker: str = typer.Argument(..., help="Ticker symbol"),
    range: str = typer.Option("2y", "--range", "-r", help="Time range (1y, 2y, 5y)"),
    save: str | None = typer.Option(None, "--save", "-s", help="Save to file path"),
):
    """
    Plot stock price with all EMAs and SMAs (10, 50, 200).

    Examples:
        tb plot all AAPL
        tb plot all MSFT --range 1y
        tb plot all GOOGL --save chart.png
    """
    _plot_chart(
        ticker=ticker,
        show_price=True,
        show_sma_10=True,
        show_sma_50=True,
        show_sma_200=True,
        show_ema_10=True,
        show_ema_50=True,
        show_ema_200=True,
        show_crosses=True,
        range=range,
        save_path=save,
    )
    console.print(f"[green]✓ Plotted {ticker.upper()} with all indicators[/green]")


@plot_app.command("ema")
def plot_ema(
    ticker: str = typer.Argument(..., help="Ticker symbol"),
    range: str = typer.Option("2y", "--range", "-r", help="Time range (1y, 2y, 5y)"),
    save: str | None = typer.Option(None, "--save", "-s", help="Save to file path"),
):
    """
    Plot stock price with all EMAs (10, 50, 200).

    Examples:
        tb plot ema AAPL
        tb plot ema MSFT --range 1y
    """
    _plot_chart(
        ticker=ticker,
        show_price=True,
        show_ema_10=True,
        show_ema_50=True,
        show_ema_200=True,
        range=range,
        save_path=save,
    )
    console.print(f"[green]✓ Plotted {ticker.upper()} with all EMAs[/green]")


@plot_app.command("sma")
def plot_sma(
    ticker: str = typer.Argument(..., help="Ticker symbol"),
    range: str = typer.Option("2y", "--range", "-r", help="Time range (1y, 2y, 5y)"),
    save: str | None = typer.Option(None, "--save", "-s", help="Save to file path"),
):
    """
    Plot stock price with all SMAs (10, 50, 200).

    Examples:
        tb plot sma AAPL
        tb plot sma MSFT --range 1y
    """
    _plot_chart(
        ticker=ticker,
        show_price=True,
        show_sma_10=True,
        show_sma_50=True,
        show_sma_200=True,
        range=range,
        save_path=save,
    )
    console.print(f"[green]✓ Plotted {ticker.upper()} with all SMAs[/green]")


@plot_app.command("price")
def plot_price(
    ticker: str = typer.Argument(..., help="Ticker symbol"),
    range: str = typer.Option("2y", "--range", "-r", help="Time range (1y, 2y, 5y)"),
    save: str | None = typer.Option(None, "--save", "-s", help="Save to file path"),
):
    """
    Plot stock price only.

    Examples:
        tb plot price AAPL
        tb plot price MSFT --range 1y
    """
    _plot_chart(ticker=ticker, show_price=True, range=range, save_path=save)
    console.print(f"[green]✓ Plotted {ticker.upper()} price[/green]")


@plot_app.command("volume")
def plot_volume(
    ticker: str = typer.Argument(..., help="Ticker symbol"),
    range: str = typer.Option("2y", "--range", "-r", help="Time range (1y, 2y, 5y)"),
    save: str | None = typer.Option(None, "--save", "-s", help="Save to file path"),
):
    """
    Plot stock price with volume bars.

    Volume bars are colored green (up day) / red (down day).

    Examples:
        tb plot volume AAPL
        tb plot volume TSLA --range 1y --save tsla_volume.png
    """
    _plot_chart(
        ticker=ticker, show_price=True, show_volume=True, range=range, save_path=save
    )
    console.print(f"[green]✓ Plotted {ticker.upper()} with volume[/green]")


@plot_app.command("rsi")
def plot_rsi(
    ticker: str = typer.Argument(..., help="Ticker symbol"),
    range: str = typer.Option("2y", "--range", "-r", help="Time range (1y, 2y, 5y)"),
    save: str | None = typer.Option(None, "--save", "-s", help="Save to file path"),
):
    """
    Plot stock price with RSI(14) subplot.

    Highlights oversold (<30) and overbought (>70) zones.

    Examples:
        tb plot rsi AAPL
        tb plot rsi NVDA --range 1y
    """
    _plot_chart(
        ticker=ticker, show_price=True, show_rsi=True, range=range, save_path=save
    )
    console.print(f"[green]✓ Plotted {ticker.upper()} with RSI[/green]")


@plot_app.command("macd")
def plot_macd(
    ticker: str = typer.Argument(..., help="Ticker symbol"),
    range: str = typer.Option("2y", "--range", "-r", help="Time range (1y, 2y, 5y)"),
    save: str | None = typer.Option(None, "--save", "-s", help="Save to file path"),
):
    """
    Plot stock price with MACD / signal / histogram subplot.

    Examples:
        tb plot macd AAPL
        tb plot macd MSFT --range 1y --save msft_macd.png
    """
    _plot_chart(
        ticker=ticker, show_price=True, show_macd=True, range=range, save_path=save
    )
    console.print(f"[green]✓ Plotted {ticker.upper()} with MACD[/green]")


@plot_app.command("splits")
def plot_splits(
    ticker: str = typer.Argument(..., help="Ticker symbol"),
    range: str = typer.Option("2y", "--range", "-r", help="Time range (1y, 2y, 5y)"),
    save: str | None = typer.Option(None, "--save", "-s", help="Save to file path"),
):
    """
    Plot stock price with corporate-action markers (splits & dividends).

    Splits are shown as dashed yellow lines; dividends as dotted cyan lines.

    Examples:
        tb plot splits AAPL --range 5y
        tb plot splits NVDA --range 5y --save nvda_splits.png
    """
    _plot_chart(
        ticker=ticker, show_price=True, show_splits=True, range=range, save_path=save
    )
    console.print(f"[green]✓ Plotted {ticker.upper()} with corporate actions[/green]")


@plot_app.command("full")
def plot_full(
    ticker: str = typer.Argument(..., help="Ticker symbol"),
    range: str = typer.Option("2y", "--range", "-r", help="Time range (1y, 2y, 5y)"),
    save: str | None = typer.Option(None, "--save", "-s", help="Save to file path"),
):
    """
    Comprehensive multi-panel chart: price + SMA/EMA + volume + RSI + MACD + splits.

    The most complete view of a stock's technical picture.

    Examples:
        tb plot full AAPL
        tb plot full MSFT --range 1y --save msft_full.png
    """
    _plot_chart(
        ticker=ticker,
        show_price=True,
        show_sma_50=True,
        show_sma_200=True,
        show_ema_10=True,
        show_ema_50=True,
        show_volume=True,
        show_rsi=True,
        show_macd=True,
        show_splits=True,
        show_crosses=True,
        range=range,
        save_path=save,
    )
    console.print(f"[green]✓ Plotted {ticker.upper()} — full technical view[/green]")


@plot_app.command("custom")
def plot_custom(
    ticker: str = typer.Argument(..., help="Ticker symbol"),
    price: bool = typer.Option(True, "--price/--no-price", help="Show price"),
    sma_10: bool = typer.Option(False, "--sma-10/--no-sma-10", help="Show SMA 10"),
    sma_50: bool = typer.Option(False, "--sma-50/--no-sma-50", help="Show SMA 50"),
    sma_200: bool = typer.Option(False, "--sma-200/--no-sma-200", help="Show SMA 200"),
    ema_10: bool = typer.Option(False, "--ema-10/--no-ema-10", help="Show EMA 10"),
    ema_50: bool = typer.Option(False, "--ema-50/--no-ema-50", help="Show EMA 50"),
    ema_200: bool = typer.Option(False, "--ema-200/--no-ema-200", help="Show EMA 200"),
    ema_12: bool = typer.Option(
        False, "--ema-12/--no-ema-12", help="Show EMA 12 (fast MACD component)"
    ),
    ema_26: bool = typer.Option(
        False, "--ema-26/--no-ema-26", help="Show EMA 26 (slow MACD component)"
    ),
    volume: bool = typer.Option(False, "--volume/--no-volume", help="Show volume bars"),
    rsi: bool = typer.Option(False, "--rsi/--no-rsi", help="Show RSI(14) subplot"),
    macd: bool = typer.Option(False, "--macd/--no-macd", help="Show MACD subplot"),
    splits: bool = typer.Option(
        False, "--splits/--no-splits", help="Show corporate actions"
    ),
    crosses: bool = typer.Option(
        False, "--crosses/--no-crosses", help="Show golden/death cross"
    ),
    range: str = typer.Option("2y", "--range", "-r", help="Time range (1y, 2y, 5y)"),
    save: str | None = typer.Option(None, "--save", "-s", help="Save to file path"),
):
    """
    Plot custom combination of price, overlays, and subplots.

    Examples:
        tb plot custom AAPL --price --ema-50 --rsi
        tb plot custom MSFT --price --sma-50 --sma-200 --volume --macd
        tb plot custom GOOGL --price --ema-10 --ema-50 --sma-200 --splits --crosses
    """
    _plot_chart(
        ticker=ticker,
        show_price=price,
        show_sma_10=sma_10,
        show_sma_50=sma_50,
        show_sma_200=sma_200,
        show_ema_10=ema_10,
        show_ema_50=ema_50,
        show_ema_200=ema_200,
        show_ema_12=ema_12,
        show_ema_26=ema_26,
        show_volume=volume,
        show_rsi=rsi,
        show_macd=macd,
        show_splits=splits,
        show_crosses=crosses,
        range=range,
        save_path=save,
    )
    console.print(f"[green]✓ Plotted {ticker.upper()} with custom indicators[/green]")
