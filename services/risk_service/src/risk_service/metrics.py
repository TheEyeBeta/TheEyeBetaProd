"""Portfolio metrics computation and persistence."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import numpy as np
import psycopg
import structlog

from risk_service.models import (
    ComputedPortfolioMetrics,
    PortfolioMandate,
    PortfolioRiskContext,
    PositionRow,
)
from zinc_native import risk

log = structlog.get_logger()


def _compute_hhi(weights: np.ndarray) -> float:
    if weights.size == 0:
        return 0.0
    return float(np.sum(np.square(weights)))


def compute_metrics_from_context(ctx: PortfolioRiskContext) -> ComputedPortfolioMetrics:
    """Recompute VaR, CVaR, HHI, exposure from a portfolio context."""
    values = np.array([abs(p.market_value) for p in ctx.positions], dtype=float)
    signed = np.array([p.market_value for p in ctx.positions], dtype=float)
    nav = max(ctx.nav, 1e-9)
    weights = values / nav if values.size else np.array([])
    gross = float(np.sum(values) / nav)
    net = float(np.sum(signed) / nav)
    samples = ctx.return_samples
    var_95 = abs(float(risk.historical_var(samples, 0.05))) if samples.size else 0.0
    cvar_95 = abs(float(risk.cvar(samples, 0.05))) if samples.size else 0.0
    max_dd = float(risk.max_drawdown(ctx.wealth_30d)) if ctx.wealth_30d.size else 0.0
    hhi = _compute_hhi(weights)

    cluster_exposures: dict[str, float] = {}
    for pos in ctx.positions:
        cluster_exposures[pos.cluster] = cluster_exposures.get(pos.cluster, 0.0) + abs(
            pos.market_value,
        )

    raw: dict[str, Any] = {
        "cluster_exposures": {k: v / nav for k, v in cluster_exposures.items()},
        "position_count": len(ctx.positions),
    }

    return ComputedPortfolioMetrics(
        portfolio_id=ctx.portfolio_id,
        var_95=var_95,
        cvar_95=cvar_95,
        max_drawdown=max_dd,
        gross_exposure=gross * nav,
        net_exposure=net * nav,
        beta_spy=ctx.beta_spy,
        concentration_hhi=hhi,
        raw=raw,
    )


async def insert_risk_metrics(dsn: str, metrics: ComputedPortfolioMetrics) -> None:
    """Append one ``risk_metrics`` hypertable row."""
    async with await psycopg.AsyncConnection.connect(dsn) as conn:
        await conn.execute(
            """
            INSERT INTO theeyebeta.risk_metrics
                (portfolio_id, ts, var_95, cvar_95, max_drawdown,
                 gross_exposure, net_exposure, beta_spy, concentration_hhi, raw)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
            """,
            (
                UUID(metrics.portfolio_id),
                datetime.now(tz=UTC),
                metrics.var_95,
                metrics.cvar_95,
                metrics.max_drawdown,
                metrics.gross_exposure,
                metrics.net_exposure,
                metrics.beta_spy,
                metrics.concentration_hhi,
                json.dumps(metrics.raw),
            ),
        )
        await conn.commit()
    log.info("risk_metrics_inserted", portfolio_id=metrics.portfolio_id)


async def load_portfolio_context(
    dsn: str,
    portfolio_id: str,
    *,
    instrument_id: int | None = None,
    default_price: float = 100.0,
) -> PortfolioRiskContext:
    """Load portfolio mandate, positions, and latest metrics from Postgres."""
    async with await psycopg.AsyncConnection.connect(dsn) as conn:
        cur = await conn.execute(
            """
            SELECT mandate
              FROM theeyebeta.portfolios
             WHERE id = %s
            """,
            (UUID(portfolio_id),),
        )
        row = await cur.fetchone()
        if row is None:
            msg = f"portfolio {portfolio_id} not found"
            raise ValueError(msg)
        mandate = PortfolioMandate.model_validate(row[0] or {})

        cur = await conn.execute(
            """
            SELECT p.instrument_id, i.symbol,
                   COALESCE(i.metadata->>'sector', 'unknown') AS sector,
                   COALESCE(i.metadata->>'cluster', 'default') AS cluster,
                   p.qty,
                   COALESCE(p.market_value, p.qty * p.avg_entry_price) AS market_value
              FROM theeyebeta.positions p
              JOIN theeyebeta.instruments i ON i.id = p.instrument_id
             WHERE p.portfolio_id = %s
            """,
            (UUID(portfolio_id),),
        )
        pos_rows = await cur.fetchall()

        cur = await conn.execute(
            """
            SELECT var_95, raw, beta_spy
              FROM theeyebeta.risk_metrics
             WHERE portfolio_id = %s
             ORDER BY ts DESC
             LIMIT 1
            """,
            (UUID(portfolio_id),),
        )
        metrics_row = await cur.fetchone()

    positions = [
        PositionRow(
            instrument_id=int(r[0]),
            symbol=str(r[1]),
            sector=str(r[2]),
            cluster=str(r[3]),
            qty=float(r[4]),
            market_value=float(r[5]),
        )
        for r in pos_rows
    ]
    nav = sum(abs(p.market_value) for p in positions) or 1_000_000.0

    raw = metrics_row[1] if metrics_row else {}
    if isinstance(raw, str):
        raw = json.loads(raw)
    cluster_exposures_raw = (raw or {}).get("cluster_exposures") or {}
    cluster_exposures = {k: float(v) * nav for k, v in cluster_exposures_raw.items()}

    return_samples = np.array((raw or {}).get("return_samples") or [-0.01, 0.005, -0.02, 0.01])
    wealth_30d = np.array((raw or {}).get("wealth_30d") or _default_wealth(nav))
    beta = float(metrics_row[2]) if metrics_row and metrics_row[2] is not None else 1.0

    return PortfolioRiskContext(
        portfolio_id=portfolio_id,
        nav=nav,
        mandate=mandate,
        positions=positions,
        return_samples=return_samples,
        wealth_30d=wealth_30d,
        cluster_exposures=cluster_exposures,
        beta_spy=beta,
    )


def _default_wealth(nav: float) -> list[float]:
    return [nav, nav * 0.92, nav * 0.88, nav * 0.90, nav * 0.87]
