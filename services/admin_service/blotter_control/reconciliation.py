"""On-demand broker vs local reconciliation."""

from __future__ import annotations

from typing import Any


def diff_positions(
    broker: list[dict[str, Any]],
    local: list[dict[str, Any]],
    *,
    qty_tolerance: float = 1e-4,
) -> list[dict[str, Any]]:
    broker_map = {str(p["symbol"]): float(p.get("qty") or 0) for p in broker}
    local_map = {str(p["symbol"]): float(p.get("qty") or 0) for p in local}
    symbols = set(broker_map) | set(local_map)
    drifts: list[dict[str, Any]] = []
    for symbol in sorted(symbols):
        b_qty = broker_map.get(symbol, 0.0)
        l_qty = local_map.get(symbol, 0.0)
        if abs(b_qty - l_qty) > qty_tolerance:
            drifts.append(
                {
                    "kind": "position",
                    "symbol": symbol,
                    "broker_qty": b_qty,
                    "local_qty": l_qty,
                },
            )
    return drifts


def diff_orders(
    broker: list[dict[str, Any]],
    local: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    broker_by_client = {
        str(o.get("client_order_id") or ""): o for o in broker if o.get("client_order_id")
    }
    drifts: list[dict[str, Any]] = []
    for local_order in local:
        client_id = str(local_order.get("client_order_id") or "")
        remote = broker_by_client.get(client_id)
        if remote is None:
            drifts.append(
                {
                    "kind": "order_missing_on_broker",
                    "client_order_id": client_id,
                    "local_status": local_order.get("status"),
                },
            )
            continue
        if abs(float(remote.get("filled_qty") or 0) - float(local_order.get("filled_qty") or 0)) > 1e-4:
            drifts.append(
                {
                    "kind": "order_fill_qty",
                    "client_order_id": client_id,
                    "broker_filled_qty": float(remote.get("filled_qty") or 0),
                    "local_filled_qty": float(local_order.get("filled_qty") or 0),
                },
            )
    return drifts
