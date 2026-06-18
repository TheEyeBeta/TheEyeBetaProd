import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { dataGet } from "../api/http";
import { asArray, asRecord, formatNumber } from "../api/normalizers";
import type { DataTableRow, DataTablesResponse, MacroSeriesListResponse } from "../api/types";
import { DataTable } from "../components/DataTable";
import { EmptyState } from "../components/EmptyState";
import { Panel } from "../components/Panel";

type GenericRow = Record<string, unknown>;

export function DataPanel() {
  const [ticker, setTicker] = useState("AAPL");

  const tables = useQuery({
    queryKey: ["data", "tables"],
    queryFn: () => dataGet<DataTablesResponse>("/api/v1/data/tables"),
    staleTime: 60000
  });
  const macroSeries = useQuery({
    queryKey: ["data", "macro-series-inventory"],
    queryFn: () => dataGet<MacroSeriesListResponse>("/v1/macro/series"),
    staleTime: 300000
  });
  const fundamentals = useQuery({
    queryKey: ["data", "fundamentals", ticker],
    queryFn: () => dataGet<unknown>(`/api/v1/tickers/${encodeURIComponent(ticker)}/fundamentals`),
    enabled: Boolean(ticker)
  });
  const actions = useQuery({
    queryKey: ["data", "corp-actions", ticker],
    queryFn: () =>
      dataGet<unknown>(`/api/v1/tickers/${encodeURIComponent(ticker)}/corporate-actions`, {
        limit: 20
      }),
    enabled: Boolean(ticker)
  });

  const tableRows = tables.data?.tables ?? [];
  const totalRows = tableRows.reduce((sum, row) => sum + (row.row_count_estimate ?? 0), 0);
  const actionRows = asArray<GenericRow>(actions.data, ["actions"]);
  const fundamentalsRecord = asRecord(fundamentals.data);

  return (
    <div className="grid h-full grid-cols-[1.2fr_0.8fr] grid-rows-[92px_1fr] gap-2">
      <Panel title="Data Estate" className="col-span-2">
        <div className="grid h-full grid-cols-4 gap-2 text-xs">
          <div className="border border-terminal-border p-2">
            <div className="uppercase text-terminal-muted">Tables</div>
            <div className="font-mono text-2xl text-terminal-primary">{tableRows.length}</div>
          </div>
          <div className="border border-terminal-border p-2">
            <div className="uppercase text-terminal-muted">Estimated Rows</div>
            <div className="font-mono text-2xl text-terminal-text">
              {formatNumber(totalRows, 0)}
            </div>
          </div>
          <div className="border border-terminal-border p-2">
            <div className="uppercase text-terminal-muted">Macro Series</div>
            <div className="font-mono text-2xl text-terminal-secondary">
              {macroSeries.data?.count ?? macroSeries.data?.series?.length ?? 0}
            </div>
          </div>
          <label className="border border-terminal-border p-2 uppercase text-terminal-muted">
            Ticker drilldown
            <input
              value={ticker}
              onChange={(event) => setTicker(event.target.value.toUpperCase())}
              className="mt-1 h-7 w-full border border-terminal-border bg-terminal-bg px-2 font-mono text-terminal-text outline-none focus:border-terminal-primary"
            />
          </label>
        </div>
      </Panel>

      <Panel title="DataAPI Tables">
        <DataTable<DataTableRow>
          rows={tableRows}
          empty="No data tables returned; token may lack table-level authorization"
          getKey={(row, index) => row.name ?? String(index)}
          columns={[
            { key: "name", header: "Name", render: (row) => row.name ?? "--" },
            { key: "type", header: "Type", render: (row) => row.table_type ?? "--" },
            {
              key: "rows",
              header: "Rows",
              render: (row) => formatNumber(row.row_count_estimate, 0)
            },
            {
              key: "access",
              header: "Access",
              render: (row) => (row.basic_access ? "basic" : "restricted")
            }
          ]}
        />
      </Panel>

      <div className="grid min-h-0 grid-rows-[1fr_1fr] gap-2">
        <Panel title="Fundamentals">
          {Object.keys(fundamentalsRecord).length === 0 ? (
            <EmptyState label="No fundamentals returned" />
          ) : (
            <pre className="whitespace-pre-wrap break-words font-mono text-xs text-terminal-text">
              {JSON.stringify(fundamentalsRecord, null, 2)}
            </pre>
          )}
        </Panel>
        <Panel title="Corporate Actions">
          <DataTable<GenericRow>
            rows={actionRows}
            empty="No corporate actions returned"
            getKey={(row, index) => String(row.id ?? row.action_date ?? index)}
            columns={[
              {
                key: "date",
                header: "Date",
                render: (row) => String(row.action_date ?? row.date ?? "--")
              },
              {
                key: "type",
                header: "Type",
                render: (row) => String(row.action_type ?? row.type ?? "--")
              },
              {
                key: "value",
                header: "Value",
                render: (row) => String(row.amount ?? row.ratio ?? row.value ?? "--")
              }
            ]}
          />
        </Panel>
      </div>
    </div>
  );
}
