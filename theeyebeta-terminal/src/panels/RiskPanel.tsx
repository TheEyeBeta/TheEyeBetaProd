import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { adminGet, adminPost } from "../api/http";
import { asArray, asRecord, formatDate, formatNumber } from "../api/normalizers";
import { ActionButton } from "../components/ActionButton";
import { DataTable } from "../components/DataTable";
import { EmptyState } from "../components/EmptyState";
import { Panel } from "../components/Panel";

type RiskMetric = Record<string, unknown>;

export function RiskPanel() {
  const queryClient = useQueryClient();
  const metrics = useQuery({
    queryKey: ["admin", "risk-metrics"],
    queryFn: () => adminGet<unknown>("/admin/risk/metrics"),
    refetchInterval: 30000
  });

  const compute = useMutation({
    mutationFn: () => adminPost<unknown>("/admin/risk/compute"),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["admin", "risk-metrics"] });
    }
  });

  const rows = asArray<RiskMetric>(metrics.data, ["metrics", "rows", "portfolios"]);
  const summary = asRecord(metrics.data);

  return (
    <div className="grid h-full grid-cols-[1.2fr_0.8fr] gap-2">
      <Panel
        title="Risk Metrics"
        action={
          <ActionButton
            variant="secondary"
            onClick={() => compute.mutate()}
            disabled={compute.isPending}
          >
            Compute
          </ActionButton>
        }
      >
        {rows.length === 0 ? (
          <EmptyState label="No portfolios configured - OMS requires a portfolio to compute risk metrics" />
        ) : (
          <DataTable<RiskMetric>
            rows={rows}
            empty="No risk metrics returned"
            getKey={(row, index) => String(row.portfolio_id ?? row.account_id ?? index)}
            columns={[
              {
                key: "portfolio",
                header: "Portfolio",
                render: (row) => String(row.portfolio_id ?? row.account_id ?? "--")
              },
              {
                key: "var",
                header: "VaR",
                render: (row) => formatNumber(row.var ?? row.value_at_risk)
              },
              {
                key: "exposure",
                header: "Exposure",
                render: (row) => formatNumber(row.exposure ?? row.gross_exposure)
              },
              { key: "leverage", header: "Lev", render: (row) => formatNumber(row.leverage, 3) },
              {
                key: "updated",
                header: "Updated",
                render: (row) => formatDate(String(row.updated_at ?? row.ts ?? ""))
              }
            ]}
          />
        )}
      </Panel>

      <Panel title="Risk Payload / Status">
        <div className="space-y-2 text-xs">
          {compute.data ? (
            <div className="border border-terminal-primary p-2 text-terminal-primary">
              <div className="uppercase">Compute trigger response</div>
              <pre className="mt-2 whitespace-pre-wrap font-mono text-terminal-text">
                {JSON.stringify(compute.data, null, 2)}
              </pre>
            </div>
          ) : null}
          {compute.error ? (
            <div className="border border-terminal-danger p-2 text-terminal-danger">
              {compute.error instanceof Error ? compute.error.message : "Risk compute failed"}
            </div>
          ) : null}
          {Object.keys(summary).length === 0 ? (
            <EmptyState label="No risk summary returned" />
          ) : (
            Object.entries(summary)
              .filter(([, value]) => !Array.isArray(value))
              .map(([key, value]) => (
                <div key={key} className="border border-terminal-border p-2">
                  <div className="uppercase text-terminal-muted">{key}</div>
                  <div className="break-words font-mono text-terminal-text">
                    {JSON.stringify(value)}
                  </div>
                </div>
              ))
          )}
        </div>
      </Panel>
    </div>
  );
}
