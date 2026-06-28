import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { dataGet } from "../api/http";
import { formatDate, formatNumber } from "../api/normalizers";
import type { SignalRow, SignalsLatestResponse } from "../api/types";
import { DataTable } from "../components/DataTable";
import { Panel } from "../components/Panel";

export function SignalsPanel() {
  const [ticker, setTicker] = useState("");
  const [strategy, setStrategy] = useState("");

  const latest = useQuery({
    queryKey: ["data", "signals-latest"],
    queryFn: () => dataGet<SignalsLatestResponse>("/api/v1/signals/latest", { limit: 50 }),
    refetchInterval: 5000
  });

  const rows = useMemo(() => {
    const needleTicker = ticker.trim().toLowerCase();
    const needleStrategy = strategy.trim().toLowerCase();
    return (latest.data?.signals ?? []).filter((row) => {
      const rowTicker = String(row.ticker ?? row.symbol ?? "").toLowerCase();
      const rowStrategy = String(row.strategy_name ?? row.strategy ?? "").toLowerCase();
      return (
        (!needleTicker || rowTicker.includes(needleTicker)) &&
        (!needleStrategy || rowStrategy.includes(needleStrategy))
      );
    });
  }, [latest.data?.signals, strategy, ticker]);

  const chartRows = useMemo(() => {
    const counts = new Map<string, number>();
    rows.forEach((row) => {
      const key = row.strategy_name ?? row.strategy ?? "unknown";
      counts.set(key, (counts.get(key) ?? 0) + 1);
    });
    return Array.from(counts.entries()).map(([name, count]) => ({ name, count }));
  }, [rows]);

  return (
    <div className="grid h-full grid-cols-[1.35fr_0.9fr] gap-2">
      <Panel
        title="Latest Signals 50"
        action={
          <div className="flex gap-2">
            <input
              value={ticker}
              onChange={(event) => setTicker(event.target.value)}
              placeholder="TICKER"
              className="h-6 w-28 border border-terminal-border bg-terminal-bg px-2 font-mono text-terminal-text outline-none focus:border-terminal-primary"
            />
            <input
              value={strategy}
              onChange={(event) => setStrategy(event.target.value)}
              placeholder="STRATEGY"
              className="h-6 w-36 border border-terminal-border bg-terminal-bg px-2 font-mono text-terminal-text outline-none focus:border-terminal-primary"
            />
          </div>
        }
      >
        <DataTable<SignalRow>
          rows={rows}
          empty="No latest signals returned"
          getKey={(row, index) => row.id ?? `${row.ticker ?? row.symbol}-${index}`}
          columns={[
            {
              key: "ts",
              header: "TS",
              render: (row) => formatDate(row.created_at ?? row.timestamp)
            },
            { key: "ticker", header: "Ticker", render: (row) => row.ticker ?? row.symbol ?? "--" },
            {
              key: "strategy",
              header: "Strategy",
              render: (row) => row.strategy_name ?? row.strategy ?? "--"
            },
            { key: "signal", header: "Signal", render: (row) => row.signal ?? row.side ?? "--" },
            {
              key: "confidence",
              header: "Conf",
              render: (row) => formatNumber(row.confidence ?? row.score, 3)
            },
            {
              key: "entry",
              header: "Entry",
              render: (row) => formatNumber(row.entry ?? row.entry_price)
            },
            {
              key: "target",
              header: "Target",
              render: (row) => formatNumber(row.target ?? row.target_price)
            },
            {
              key: "stop",
              header: "Stop",
              render: (row) => formatNumber(row.stop ?? row.stop_loss)
            }
          ]}
        />
      </Panel>

      <Panel title="Signal Count By Strategy" action="refresh 5s">
        <div className="h-full min-h-72">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={chartRows} margin={{ top: 12, right: 8, bottom: 20, left: 0 }}>
              <CartesianGrid stroke="#1A1A2E" vertical={false} />
              <XAxis dataKey="name" stroke="#6B7280" tick={{ fontSize: 10 }} />
              <YAxis stroke="#6B7280" tick={{ fontSize: 10 }} allowDecimals={false} />
              <Tooltip
                contentStyle={{
                  background: "#0D0D15",
                  border: "1px solid #1A1A2E",
                  borderRadius: 0,
                  color: "#E8E8F0",
                  fontSize: 11
                }}
              />
              <Bar dataKey="count" fill="#00FFD1" isAnimationActive={false} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </Panel>
    </div>
  );
}
