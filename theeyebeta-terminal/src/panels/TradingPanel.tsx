import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { adminGet, adminPost } from "../api/http";
import { asArray, asRecord, formatDate, formatNumber } from "../api/normalizers";
import type { PendingOrder, PendingOrdersResponse, PositionRow } from "../api/types";
import { ActionButton } from "../components/ActionButton";
import { DataTable } from "../components/DataTable";
import { EmptyState } from "../components/EmptyState";
import { Panel } from "../components/Panel";

type OrderAction = { id: string; action: "approve" | "reject" };

export function TradingPanel() {
  const queryClient = useQueryClient();
  const [ticket, setTicket] = useState({ symbol: "", side: "BUY", quantity: "100" });
  const [notice, setNotice] = useState("");

  const positions = useQuery({
    queryKey: ["admin", "broker-positions"],
    queryFn: () => adminGet<unknown>("/admin/broker/positions"),
    refetchInterval: 10000
  });
  const orders = useQuery({
    queryKey: ["admin", "pending-orders"],
    queryFn: () => adminGet<PendingOrdersResponse>("/admin/orders/pending"),
    refetchInterval: 10000
  });
  const oms = useQuery({
    queryKey: ["admin", "oms-reconciliation"],
    queryFn: () => adminGet<unknown>("/admin/oms/reconciliation"),
    refetchInterval: 15000
  });

  const orderAction = useMutation({
    mutationFn: async (input: OrderAction) => {
      if (input.action === "approve") {
        return adminPost(`/admin/orders/${encodeURIComponent(input.id)}/approve`, {
          note: "Approved from terminal"
        });
      }
      return adminPost(`/admin/orders/${encodeURIComponent(input.id)}/reject`, {
        rejection_reason: "Rejected from terminal"
      });
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["admin", "pending-orders"] });
    }
  });

  const positionRows = asArray<PositionRow>(positions.data, ["positions"]);
  const orderRows = orders.data?.orders ?? [];
  const omsRecord = asRecord(oms.data);

  function submitPaperOrder(event: React.FormEvent) {
    event.preventDefault();
    setNotice(
      `Paper order ${ticket.side} ${ticket.quantity} ${ticket.symbol || "UNKNOWN"} blocked: BACKEND_SURFACE.md exposes approve/reject/read paths, but no audited place-paper-order endpoint.`
    );
  }

  return (
    <div className="grid h-full grid-cols-[1fr_1fr] grid-rows-[1fr_1fr] gap-2">
      <Panel title="Paper Positions / Broker">
        <DataTable<PositionRow>
          rows={positionRows}
          empty="No broker positions returned"
          getKey={(row, index) => String(row.symbol ?? row.ticker ?? index)}
          columns={[
            {
              key: "symbol",
              header: "Symbol",
              render: (row) => String(row.symbol ?? row.ticker ?? "--")
            },
            {
              key: "qty",
              header: "Qty",
              render: (row) => formatNumber(row.qty ?? row.quantity, 4)
            },
            {
              key: "mv",
              header: "Market Value",
              render: (row) => formatNumber(row.market_value ?? row.value)
            },
            {
              key: "pnl",
              header: "PnL",
              render: (row) => formatNumber(row.unrealized_pl ?? row.pnl)
            }
          ]}
        />
      </Panel>

      <Panel title="Open Orders / Approval Queue">
        <DataTable<PendingOrder>
          rows={orderRows}
          empty="No pending orders returned"
          getKey={(row, index) => row.id ?? row.order_id ?? String(index)}
          columns={[
            { key: "symbol", header: "Symbol", render: (row) => row.symbol ?? row.ticker ?? "--" },
            { key: "side", header: "Side", render: (row) => row.side ?? "--" },
            {
              key: "qty",
              header: "Qty",
              render: (row) => formatNumber(row.quantity ?? row.qty, 4)
            },
            { key: "status", header: "Status", render: (row) => row.status ?? "--" },
            {
              key: "action",
              header: "Action",
              render: (row) => {
                const id = row.id ?? row.order_id;
                if (!id) return "--";
                return (
                  <div className="flex gap-1">
                    <ActionButton onClick={() => orderAction.mutate({ id, action: "approve" })}>
                      APP
                    </ActionButton>
                    <ActionButton
                      variant="danger"
                      onClick={() => orderAction.mutate({ id, action: "reject" })}
                    >
                      REJ
                    </ActionButton>
                  </div>
                );
              }
            }
          ]}
        />
      </Panel>

      <Panel title="Place Paper Order">
        <form onSubmit={submitPaperOrder} className="grid max-w-lg grid-cols-3 gap-2 text-xs">
          <label className="uppercase text-terminal-muted">
            Symbol
            <input
              value={ticket.symbol}
              onChange={(event) =>
                setTicket({ ...ticket, symbol: event.target.value.toUpperCase() })
              }
              className="mt-1 h-8 w-full border border-terminal-border bg-terminal-bg px-2 font-mono text-terminal-text outline-none focus:border-terminal-primary"
            />
          </label>
          <label className="uppercase text-terminal-muted">
            Side
            <select
              value={ticket.side}
              onChange={(event) => setTicket({ ...ticket, side: event.target.value })}
              className="mt-1 h-8 w-full border border-terminal-border bg-terminal-bg px-2 font-mono text-terminal-text outline-none focus:border-terminal-primary"
            >
              <option>BUY</option>
              <option>SELL</option>
            </select>
          </label>
          <label className="uppercase text-terminal-muted">
            Quantity
            <input
              value={ticket.quantity}
              onChange={(event) => setTicket({ ...ticket, quantity: event.target.value })}
              className="mt-1 h-8 w-full border border-terminal-border bg-terminal-bg px-2 font-mono text-terminal-text outline-none focus:border-terminal-primary"
            />
          </label>
          <div className="col-span-3">
            <ActionButton type="submit" variant="secondary">
              Validate Surface
            </ActionButton>
          </div>
        </form>
        {notice ? (
          <div className="mt-3 border border-terminal-secondary p-2 text-xs text-terminal-secondary">
            {notice}
          </div>
        ) : null}
      </Panel>

      <Panel title="OMS Health / Reconciliation">
        {Object.keys(omsRecord).length === 0 ? (
          <EmptyState label="No OMS reconciliation payload returned" />
        ) : (
          <div className="grid grid-cols-2 gap-2 text-xs">
            {Object.entries(omsRecord).map(([key, value]) => (
              <div key={key} className="border border-terminal-border p-2">
                <div className="uppercase text-terminal-muted">{key}</div>
                <div className="mt-1 break-words font-mono text-terminal-text">
                  {typeof value === "string" && value.includes("T")
                    ? formatDate(value)
                    : JSON.stringify(value)}
                </div>
              </div>
            ))}
          </div>
        )}
      </Panel>
    </div>
  );
}
