"""Six ordered pre-trade risk checks (Part 9.1)."""

from __future__ import annotations

from collections.abc import Callable

import numpy as np
import structlog

from risk_service.models import (
    CheckResult,
    OrderProposal,
    PortfolioRiskContext,
    RiskOutcome,
    RiskValidationResult,
)
from zinc_native import risk

log = structlog.get_logger()


def _signed_qty(side: str, qty: float) -> float:
    return qty if side.lower() == "buy" else -qty


def _position_after(positions: list, instrument_id: int, delta_value: float) -> dict[int, float]:
    values: dict[int, float] = {p.instrument_id: p.market_value for p in positions}
    values[instrument_id] = values.get(instrument_id, 0.0) + delta_value
    return {iid: val for iid, val in values.items() if abs(val) > 1e-9}


def _weights_from_values(values: dict[int, float], nav: float) -> np.ndarray:
    if nav <= 0:
        return np.array([])
    ordered = np.array(list(values.values()), dtype=float)
    return ordered / nav


def _compute_hhi(weights: np.ndarray) -> float:
    if weights.size == 0:
        return 0.0
    return float(np.sum(np.square(weights)))


class OrderRiskValidator:
    """Run six mandate checks in fixed order; first BLOCK stops further escalation."""

    def __init__(
        self,
        checks: list[Callable[[PortfolioRiskContext, OrderProposal], CheckResult]] | None = None,
    ) -> None:
        self._checks = checks or [
            self._check_position_size_pct,
            self._check_sector_exposure,
            self._check_correlation_cluster_exposure,
            self._check_portfolio_var_95,
            self._check_drawdown_circuit_breaker,
            self._check_concentration_hhi,
        ]

    def validate(
        self,
        context: PortfolioRiskContext,
        order: OrderProposal,
    ) -> RiskValidationResult:
        """Execute checks in order and aggregate outcome."""
        results: list[CheckResult] = []
        aggregate = RiskOutcome.ALLOW
        failed: list[str] = []
        metrics: dict[str, float] = {}

        for check in self._checks:
            hit = check(context, order)
            results.append(hit)
            metrics.update(hit.metrics)
            if hit.outcome == RiskOutcome.BLOCK:
                aggregate = RiskOutcome.BLOCK
                failed.append(hit.name)
                break
            if hit.outcome == RiskOutcome.WARN and aggregate == RiskOutcome.ALLOW:
                aggregate = RiskOutcome.WARN
                failed.append(hit.name)

        reason = "all checks passed"
        if failed:
            reason = "; ".join(r.detail for r in results if r.name in failed)

        return RiskValidationResult(
            outcome=aggregate,
            reason=reason,
            failed_checks=failed,
            metrics=metrics,
            check_results=results,
        )

    def _check_position_size_pct(
        self,
        ctx: PortfolioRiskContext,
        order: OrderProposal,
    ) -> CheckResult:
        order_value = order.qty * order.price
        delta = order_value if order.side.lower() == "buy" else -order_value
        post_values = _position_after(ctx.positions, order.instrument_id, delta)
        max_pct = max((abs(v) / ctx.nav for v in post_values.values()), default=0.0)
        limit = ctx.mandate.max_position_pct
        outcome = RiskOutcome.ALLOW if max_pct <= limit else RiskOutcome.BLOCK
        return CheckResult(
            name="position_size_pct",
            outcome=outcome,
            detail=f"position_size_pct {max_pct:.4f} vs limit {limit:.4f}",
            metrics={"position_size_pct": max_pct},
        )

    def _check_sector_exposure(
        self,
        ctx: PortfolioRiskContext,
        order: OrderProposal,
    ) -> CheckResult:
        sector_totals: dict[str, float] = {}
        for pos in ctx.positions:
            sector_totals[pos.sector] = sector_totals.get(pos.sector, 0.0) + abs(pos.market_value)
        order_value = abs(order.qty * order.price)
        sector_totals[order.sector] = sector_totals.get(order.sector, 0.0) + order_value
        max_sector = max((v / ctx.nav for v in sector_totals.values()), default=0.0)
        limit = ctx.mandate.max_sector_pct
        outcome = RiskOutcome.ALLOW if max_sector <= limit else RiskOutcome.BLOCK
        return CheckResult(
            name="sector_exposure",
            outcome=outcome,
            detail=f"sector_exposure {max_sector:.4f} vs limit {limit:.4f}",
            metrics={"sector_exposure_pct": max_sector},
        )

    def _check_correlation_cluster_exposure(
        self,
        ctx: PortfolioRiskContext,
        order: OrderProposal,
    ) -> CheckResult:
        cluster_totals = dict(ctx.cluster_exposures)
        order_value = abs(order.qty * order.price)
        cluster_totals[order.cluster] = cluster_totals.get(order.cluster, 0.0) + order_value
        max_cluster = max((v / ctx.nav for v in cluster_totals.values()), default=0.0)
        limit = ctx.mandate.max_correlation_cluster_pct
        outcome = RiskOutcome.ALLOW if max_cluster <= limit else RiskOutcome.BLOCK
        return CheckResult(
            name="correlation_cluster_exposure",
            outcome=outcome,
            detail=f"cluster_exposure {max_cluster:.4f} vs limit {limit:.4f}",
            metrics={"correlation_cluster_exposure_pct": max_cluster},
        )

    def _check_portfolio_var_95(
        self,
        ctx: PortfolioRiskContext,
        order: OrderProposal,
    ) -> CheckResult:
        order_value = order.qty * order.price
        delta = order_value if order.side.lower() == "buy" else -order_value
        post_values = _position_after(ctx.positions, order.instrument_id, delta)
        weights = _weights_from_values(post_values, ctx.nav)
        samples = ctx.return_samples
        if samples.size == 0 or weights.size == 0:
            var_pct = 0.0
        else:
            # Scale portfolio return samples by post-trade leverage proxy.
            gross = float(np.sum(np.abs(weights)))
            scaled = samples * gross
            var_abs = risk.historical_var(scaled, 0.05)
            var_pct = abs(var_abs)
        limit = ctx.mandate.max_var
        outcome = RiskOutcome.ALLOW if var_pct <= limit else RiskOutcome.BLOCK
        return CheckResult(
            name="portfolio_var_95",
            outcome=outcome,
            detail=f"portfolio_var_95 {var_pct:.4f} vs limit {limit:.4f}",
            metrics={"portfolio_var_95": var_pct},
        )

    def _check_drawdown_circuit_breaker(
        self,
        ctx: PortfolioRiskContext,
        order: OrderProposal,
    ) -> CheckResult:
        wealth = ctx.wealth_30d
        drawdown = risk.max_drawdown(wealth) if wealth.size else 0.0
        tripped = drawdown > ctx.mandate.max_drawdown_pct
        intent = order.order_intent.upper()
        side = order.side.lower()
        reducing = intent in {"REDUCE", "EXIT"} or side == "sell"
        if tripped and not reducing:
            outcome = RiskOutcome.BLOCK
            detail = (
                f"drawdown {drawdown:.4f} > {ctx.mandate.max_drawdown_pct:.4f}; "
                "only REDUCE/EXIT allowed"
            )
        elif tripped:
            outcome = RiskOutcome.WARN
            detail = f"drawdown breaker active ({drawdown:.4f}); reducing order permitted"
        else:
            outcome = RiskOutcome.ALLOW
            detail = f"drawdown {drawdown:.4f} within limit"
        return CheckResult(
            name="drawdown_circuit_breaker",
            outcome=outcome,
            detail=detail,
            metrics={"drawdown_30d": float(drawdown)},
        )

    def _check_concentration_hhi(
        self,
        ctx: PortfolioRiskContext,
        order: OrderProposal,
    ) -> CheckResult:
        order_value = order.qty * order.price
        delta = order_value if order.side.lower() == "buy" else -order_value
        post_values = _position_after(ctx.positions, order.instrument_id, delta)
        weights = _weights_from_values(post_values, ctx.nav)
        hhi = _compute_hhi(weights)
        limit = ctx.mandate.max_hhi
        outcome = RiskOutcome.ALLOW if hhi <= limit else RiskOutcome.BLOCK
        return CheckResult(
            name="concentration_hhi",
            outcome=outcome,
            detail=f"concentration_hhi {hhi:.4f} vs limit {limit:.4f}",
            metrics={"concentration_hhi": hhi},
        )
