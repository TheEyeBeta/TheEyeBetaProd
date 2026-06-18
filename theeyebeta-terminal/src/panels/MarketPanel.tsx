import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { dataGet } from "../api/http";
import { formatDate, formatNumber } from "../api/normalizers";
import type {
  MacroLatestResponse,
  MacroObservation,
  MacroRegimeResponse,
  MacroSeriesDetailResponse,
  MacroSeriesListItem,
  MacroSeriesListResponse
} from "../api/types";
import { DataTable } from "../components/DataTable";
import { EmptyState } from "../components/EmptyState";
import { Panel } from "../components/Panel";
import { Sparkline } from "../components/Sparkline";

const topCodes = "SP500,VIX,WTI,GOLD,DGS10,DXY,BAMLH0A0HYM2";

export function MarketPanel() {
  const [search, setSearch] = useState("");
  const [selected, setSelected] = useState<string>("SP500");

  const latest = useQuery({
    queryKey: ["data", "macro-latest", topCodes],
    queryFn: () => dataGet<MacroLatestResponse>("/v1/macro/latest", { codes: topCodes }),
    refetchInterval: 60000
  });

  const regime = useQuery({
    queryKey: ["data", "macro-regime"],
    queryFn: () => dataGet<MacroRegimeResponse>("/v1/macro/regime"),
    refetchInterval: 60000
  });

  const series = useQuery({
    queryKey: ["data", "macro-series"],
    queryFn: () => dataGet<MacroSeriesListResponse>("/v1/macro/series"),
    staleTime: 300000
  });

  const detail = useQuery({
    queryKey: ["data", "macro-detail", selected],
    queryFn: () =>
      dataGet<MacroSeriesDetailResponse>(`/v1/macro/series/${encodeURIComponent(selected)}`, {
        limit: 90
      }),
    enabled: Boolean(selected),
    refetchInterval: 300000
  });

  const filteredSeries = useMemo(() => {
    const needle = search.trim().toLowerCase();
    const rows = series.data?.series ?? [];
    if (!needle) return rows.slice(0, 122);
    return rows
      .filter((row) =>
        `${row.code ?? ""} ${row.name ?? ""} ${row.category ?? ""}`.toLowerCase().includes(needle)
      )
      .slice(0, 122);
  }, [search, series.data?.series]);

  const spark = useMemo(
    () =>
      (detail.data?.observations ?? [])
        .map((row) => ({ x: row.date ?? "", y: Number(row.value) }))
        .filter((row) => Number.isFinite(row.y)),
    [detail.data?.observations]
  );

  const regimeRows = Object.entries(regime.data ?? {}).map(([key, value]) => ({
    key,
    value: typeof value === "object" ? JSON.stringify(value) : String(value)
  }));

  return (
    <div className="grid h-full grid-cols-[1.15fr_1fr] grid-rows-[116px_1fr] gap-2">
      <Panel title="Macro Latest" className="col-span-2">
        <div className="grid h-full grid-cols-7 gap-2">
          {(latest.data?.observations ?? []).map((observation: MacroObservation) => (
            <button
              key={observation.code}
              onClick={() => setSelected(observation.code ?? selected)}
              className={`border p-2 text-left ${
                selected === observation.code
                  ? "border-terminal-primary shadow-neon"
                  : "border-terminal-border"
              }`}
            >
              <div className="font-mono text-xs text-terminal-primary">{observation.code}</div>
              <div className="font-mono text-xl text-terminal-text">
                {formatNumber(observation.value)}
              </div>
              <div className="truncate text-[11px] uppercase text-terminal-muted">
                {formatDate(observation.date)}
              </div>
            </button>
          ))}
          {(latest.data?.observations ?? []).length === 0 ? (
            <EmptyState label="No macro latest values returned" />
          ) : null}
        </div>
      </Panel>

      <Panel
        title="Macro Series"
        action={
          <input
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="SEARCH 122 SERIES"
            className="h-6 w-56 border border-terminal-border bg-terminal-bg px-2 font-mono text-terminal-text outline-none focus:border-terminal-primary"
          />
        }
      >
        <DataTable<MacroSeriesListItem>
          rows={filteredSeries}
          empty="No macro series returned"
          getKey={(row, index) => row.code ?? String(index)}
          columns={[
            {
              key: "code",
              header: "Code",
              render: (row) => (
                <button
                  className="text-terminal-primary"
                  onClick={() => setSelected(row.code ?? selected)}
                >
                  {row.code ?? "--"}
                </button>
              )
            },
            { key: "name", header: "Name", render: (row) => row.name ?? "--" },
            { key: "category", header: "Category", render: (row) => row.category ?? "--" },
            { key: "units", header: "Units", render: (row) => row.units ?? "--" }
          ]}
        />
      </Panel>

      <div className="grid min-h-0 grid-rows-[1fr_180px] gap-2">
        <Panel title="Macro Regime">
          <DataTable<{ key: string; value: string }>
            rows={regimeRows}
            empty="No macro regime returned"
            getKey={(row) => row.key}
            columns={[
              { key: "key", header: "Metric", render: (row) => row.key },
              { key: "value", header: "Value", render: (row) => row.value }
            ]}
          />
        </Panel>
        <Panel title={`${selected} 90D Sparkline`}>
          <Sparkline data={spark} />
        </Panel>
      </div>
    </div>
  );
}
