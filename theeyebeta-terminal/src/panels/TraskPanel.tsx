import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { adminGet, adminPost } from "../api/http";
import { formatDate } from "../api/normalizers";
import type {
  TraskBreakerDetail,
  TraskDashboardResponse,
  TraskFailureSummary,
  WorkerRegistryEntry,
  WorkersListResponse
} from "../api/types";
import { ActionButton } from "../components/ActionButton";
import { DataTable } from "../components/DataTable";
import { Panel } from "../components/Panel";
import { StatusDot } from "../components/StatusDot";

export function TraskPanel() {
  const queryClient = useQueryClient();
  const dashboard = useQuery({
    queryKey: ["admin", "trask-dashboard"],
    queryFn: () => adminGet<TraskDashboardResponse>("/admin/trask/dashboard"),
    refetchInterval: 10000
  });
  const workers = useQuery({
    queryKey: ["admin", "worker-registry"],
    queryFn: () => adminGet<WorkersListResponse>("/admin/workers"),
    refetchInterval: 15000
  });

  const resetBreaker = useMutation({
    mutationFn: (breaker: TraskBreakerDetail) => {
      const id = breaker.id;
      if (!id) throw new Error("Breaker id missing");
      if (
        !window.confirm(
          `Reset Trask breaker ${breaker.component_id ?? id}? This override will be audited.`
        )
      ) {
        return Promise.resolve({ cancelled: true });
      }
      return adminPost(`/admin/trask/breakers/${id}/reset`, {
        reason: "MASTER_ADMIN terminal breaker reset",
        consequences_acknowledged: true,
        override: true
      });
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["admin", "trask-dashboard"] });
      void queryClient.invalidateQueries({ queryKey: ["admin", "worker-registry"] });
    }
  });

  const trask = dashboard.data ?? {};
  const workerRows = workers.data?.workers ?? [];
  const sentinelRows = workerRows.filter((row) =>
    `${row.name ?? ""} ${row.worker_class ?? ""} ${row.circuit_breaker_state ?? ""}`
      .toLowerCase()
      .includes("sentinel")
  );
  const visibleSentinels = sentinelRows.length ? sentinelRows : workerRows;

  return (
    <div className="grid h-full grid-cols-[0.9fr_1.15fr_1fr] grid-rows-[120px_1fr] gap-2">
      <Panel title="Trask Component State" className="col-span-3">
        <div className="grid h-full grid-cols-4 gap-2 text-xs">
          {[
            ["Total", trask.components_total ?? 0, "text-terminal-text"],
            ["Healthy", trask.components_healthy ?? 0, "text-terminal-positive"],
            ["Degraded", trask.components_degraded ?? 0, "text-terminal-secondary"],
            ["Failed", trask.components_failed ?? 0, "text-terminal-danger"]
          ].map(([label, value, color]) => (
            <div key={label} className="border border-terminal-border p-2">
              <div className="uppercase text-terminal-muted">{label}</div>
              <div className={`font-mono text-3xl ${color}`}>{value}</div>
            </div>
          ))}
        </div>
      </Panel>

      <Panel title="Open Circuit Breakers">
        <DataTable<TraskBreakerDetail>
          rows={trask.open_breakers ?? []}
          empty="No open Trask circuit breakers"
          getKey={(row, index) => String(row.id ?? index)}
          columns={[
            { key: "state", header: "", render: (row) => <StatusDot status={row.state} /> },
            { key: "component", header: "Component", render: (row) => row.component_id ?? "--" },
            { key: "failures", header: "Fails", render: (row) => row.failure_count ?? "--" },
            { key: "opened", header: "Opened", render: (row) => formatDate(row.opened_at) },
            {
              key: "reset",
              header: "Reset",
              render: (row) => (
                <ActionButton
                  variant={row.reset_eligible ? "danger" : "secondary"}
                  disabled={!row.reset_eligible || resetBreaker.isPending}
                  onClick={() => resetBreaker.mutate(row)}
                >
                  Reset
                </ActionButton>
              )
            }
          ]}
        />
      </Panel>

      <Panel title="Sentinels / Worker Registry">
        <DataTable<WorkerRegistryEntry>
          rows={visibleSentinels}
          empty="No Trask sentinels or workers returned"
          getKey={(row, index) => row.name ?? row.worker_class ?? String(index)}
          columns={[
            { key: "state", header: "", render: (row) => <StatusDot status={row.state} /> },
            { key: "name", header: "Name", render: (row) => row.name ?? row.worker_class ?? "--" },
            { key: "alias", header: "Alias", render: (row) => row.alias ?? "--" },
            {
              key: "breaker",
              header: "Breaker",
              render: (row) => row.circuit_breaker_state ?? "--"
            },
            {
              key: "heartbeat",
              header: "Heartbeat",
              render: (row) => formatDate(row.last_heartbeat)
            }
          ]}
        />
      </Panel>

      <Panel title="Recent Trask Failures">
        <DataTable<TraskFailureSummary>
          rows={trask.recent_failures ?? []}
          empty="No recent Trask worker failures"
          getKey={(row, index) => `${row.component_id ?? index}-${row.started_at ?? ""}`}
          columns={[
            { key: "component", header: "Component", render: (row) => row.component_id ?? "--" },
            { key: "status", header: "Status", render: (row) => row.status ?? "--" },
            { key: "started", header: "Started", render: (row) => formatDate(row.started_at) },
            { key: "error", header: "Error", render: (row) => row.error_message ?? "--" }
          ]}
        />
        {(trask.degraded_components ?? []).length ? (
          <div className="mt-2 border border-terminal-secondary p-2 text-xs text-terminal-secondary">
            Degraded: {(trask.degraded_components ?? []).join(", ")}
          </div>
        ) : null}
      </Panel>
    </div>
  );
}
