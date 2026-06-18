import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { dataGet } from "../api/http";
import { asArray, asRecord, formatNumber } from "../api/normalizers";
import type {
  DataColumnRow,
  DataColumnsResponse,
  DataRowsResponse,
  DataTableRow,
  DataTablesResponse,
  MacroSeriesListResponse
} from "../api/types";
import { DataTable } from "../components/DataTable";
import { EmptyState } from "../components/EmptyState";
import { Panel } from "../components/Panel";

type GenericRow = Record<string, unknown>;

function encodeTable(table: string) {
  return encodeURIComponent(table);
}

export function DataPanel() {
  const [ticker, setTicker] = useState("AAPL");
  const [tableSearch, setTableSearch] = useState("");
  const [selectedTable, setSelectedTable] = useState("corporate_actions");
  const [rowLimit, setRowLimit] = useState(50);

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
  const columns = useQuery({
    queryKey: ["data", "table-columns", selectedTable],
    queryFn: () =>
      dataGet<DataColumnsResponse>(`/api/v1/data/tables/${encodeTable(selectedTable)}/columns`),
    enabled: Boolean(selectedTable)
  });
  const rows = useQuery({
    queryKey: ["data", "table-rows", selectedTable, rowLimit],
    queryFn: () =>
      dataGet<DataRowsResponse>(`/api/v1/data/tables/${encodeTable(selectedTable)}/rows`, {
        limit: rowLimit
      }),
    enabled: Boolean(selectedTable)
  });

  const tableRows = useMemo(() => tables.data?.tables ?? [], [tables.data?.tables]);
  const totalRows = tableRows.reduce((sum, row) => sum + (row.row_count_estimate ?? 0), 0);
  const actionRows = asArray<GenericRow>(actions.data, ["actions"]);
  const fundamentalsRecord = asRecord(fundamentals.data);
  const filteredTables = useMemo(() => {
    const needle = tableSearch.trim().toLowerCase();
    if (!needle) return tableRows;
    return tableRows.filter((row) => row.name?.toLowerCase().includes(needle));
  }, [tableRows, tableSearch]);

  useEffect(() => {
    if (!selectedTable && tableRows[0]?.name) {
      setSelectedTable(tableRows[0].name);
    }
  }, [selectedTable, tableRows]);

  return (
    <div className="grid h-full grid-cols-[0.95fr_1.35fr_0.85fr] grid-rows-[92px_1fr] gap-2">
      <Panel title="Data Estate" className="col-span-3">
        <div className="grid h-full grid-cols-5 gap-2 text-xs">
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
          <label className="border border-terminal-border p-2 uppercase text-terminal-muted">
            Row limit
            <select
              value={rowLimit}
              onChange={(event) => setRowLimit(Number(event.target.value))}
              className="mt-1 h-7 w-full border border-terminal-border bg-terminal-bg px-2 font-mono text-terminal-text outline-none focus:border-terminal-primary"
            >
              {[25, 50, 100, 250, 500].map((value) => (
                <option key={value} value={value}>
                  {value}
                </option>
              ))}
            </select>
          </label>
        </div>
      </Panel>

      <Panel
        title="DataAPI Tables"
        action={
          <input
            value={tableSearch}
            onChange={(event) => setTableSearch(event.target.value)}
            placeholder="TABLE"
            className="h-6 w-36 border border-terminal-border bg-terminal-bg px-2 font-mono text-terminal-text outline-none focus:border-terminal-primary"
          />
        }
      >
        <DataTable<DataTableRow>
          rows={filteredTables}
          empty="No data tables returned"
          getKey={(row, index) => row.name ?? String(index)}
          columns={[
            {
              key: "name",
              header: "Name",
              render: (row) => (
                <button
                  className={
                    row.name === selectedTable ? "text-terminal-primary" : "text-terminal-text"
                  }
                  onClick={() => row.name && setSelectedTable(row.name)}
                >
                  {row.name ?? "--"}
                </button>
              )
            },
            {
              key: "rows",
              header: "Rows",
              render: (row) => formatNumber(row.row_count_estimate, 0)
            }
          ]}
        />
      </Panel>

      <div className="grid min-h-0 grid-rows-[210px_1fr] gap-2">
        <Panel title={`${selectedTable || "Table"} Columns`}>
          <DataTable<DataColumnRow>
            rows={columns.data?.columns ?? []}
            empty="Select a table to inspect columns"
            getKey={(row, index) => row.name ?? String(index)}
            columns={[
              { key: "name", header: "Column", render: (row) => row.name ?? "--" },
              { key: "type", header: "Type", render: (row) => row.data_type ?? "--" },
              { key: "nullable", header: "Null", render: (row) => (row.nullable ? "yes" : "no") }
            ]}
          />
        </Panel>
        <Panel title={`${selectedTable || "Table"} Raw Rows`}>
          {(rows.data?.rows ?? []).length === 0 ? (
            <EmptyState label="No rows returned for selected table" />
          ) : (
            <pre className="whitespace-pre-wrap break-words font-mono text-[11px] leading-relaxed text-terminal-text">
              {JSON.stringify(rows.data?.rows ?? [], null, 2)}
            </pre>
          )}
        </Panel>
      </div>

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
            getKey={(row, index) => String(row.id ?? row.action_date ?? row.ex_date ?? index)}
            columns={[
              {
                key: "date",
                header: "Date",
                render: (row) => String(row.action_date ?? row.ex_date ?? row.date ?? "--")
              },
              {
                key: "type",
                header: "Type",
                render: (row) => String(row.action_type ?? row.type ?? "--")
              },
              {
                key: "value",
                header: "Value",
                render: (row) =>
                  String(
                    row.amount ?? row.cash_amount ?? row.ratio ?? row.ratio_num ?? row.value ?? "--"
                  )
              }
            ]}
          />
        </Panel>
      </div>
    </div>
  );
}
