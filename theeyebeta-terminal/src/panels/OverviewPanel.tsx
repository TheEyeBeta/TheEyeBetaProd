import { useQuery } from "@tanstack/react-query";
import { adminGet } from "../api/http";
import { formatDate, statusTone } from "../api/normalizers";
import type {
  AuditEntry,
  AuditLogPageResponse,
  OpsPulseResponse,
  PreliveResponse,
  ServiceRow,
  ServiceStatusResponse,
  TimerRow,
  TimersListResponse
} from "../api/types";
import { DataTable } from "../components/DataTable";
import { EmptyState } from "../components/EmptyState";
import { Panel } from "../components/Panel";
import { StatusDot } from "../components/StatusDot";

const serviceTargets = [
  { label: "OMS", keys: ["oms"] },
  { label: "Broker", keys: ["broker"] },
  { label: "MO", keys: ["master", "orchestrator"] },
  { label: "Risk", keys: ["risk"] },
  { label: "Compliance", keys: ["compliance"] },
  { label: "Audit", keys: ["audit"] }
];

function matchService(services: ServiceRow[], keys: string[]) {
  return services.find((service) => {
    const text = `${service.name ?? ""} ${service.unit ?? ""}`.toLowerCase();
    return keys.every((key) => text.includes(key));
  });
}

export function OverviewPanel() {
  const pulse = useQuery({
    queryKey: ["admin", "ops-pulse"],
    queryFn: () => adminGet<OpsPulseResponse>("/admin/ops/pulse"),
    refetchInterval: 10000
  });
  const services = useQuery({
    queryKey: ["admin", "services"],
    queryFn: () => adminGet<ServiceStatusResponse>("/admin/services/status"),
    refetchInterval: 15000
  });
  const prelive = useQuery({
    queryKey: ["admin", "prelive"],
    queryFn: () => adminGet<PreliveResponse>("/admin/prelive"),
    refetchInterval: 30000
  });
  const audit = useQuery({
    queryKey: ["admin", "audit-latest"],
    queryFn: () => adminGet<AuditLogPageResponse>("/admin/audit/log", { limit: 5 }),
    refetchInterval: 10000
  });
  const timers = useQuery({
    queryKey: ["admin", "timers"],
    queryFn: () => adminGet<TimersListResponse>("/admin/timers"),
    refetchInterval: 30000
  });

  const serviceRows = services.data?.services ?? pulse.data?.services ?? [];
  const checkRows = prelive.data?.checks ?? pulse.data?.prelive?.checks ?? [];
  const timerRows = timers.data?.timers ?? pulse.data?.timers ?? [];
  const auditRows = audit.data?.entries ?? [];

  return (
    <div className="grid h-full grid-cols-[1.35fr_1fr_1fr] grid-rows-[1fr_1fr] gap-2">
      <Panel title="Service Status Grid" action="OMS / Broker / MO / Risk / Compliance / Audit">
        <div className="grid grid-cols-2 gap-2">
          {serviceTargets.map((target) => {
            const service = matchService(serviceRows, target.keys);
            const health = service?.health ?? service?.state ?? "unknown";
            return (
              <div
                key={target.label}
                className="border border-terminal-border bg-terminal-panel2 p-2"
              >
                <div className="flex items-center justify-between">
                  <span className="text-xs font-semibold uppercase text-terminal-text">
                    {target.label}
                  </span>
                  <StatusDot status={health} pulse={statusTone(health) === "ok"} />
                </div>
                <div className="mt-2 font-mono text-xs text-terminal-muted">
                  {service?.name ?? "not reported"}
                </div>
                <div className="font-mono text-sm uppercase text-terminal-text">{health}</div>
              </div>
            );
          })}
        </div>
      </Panel>

      <Panel
        title="Prelive 13 Checks"
        action={prelive.data?.overall ?? pulse.data?.prelive?.overall ?? "--"}
      >
        {checkRows.length === 0 ? (
          <EmptyState label="No prelive checks returned" />
        ) : (
          <div className="space-y-1">
            {checkRows.map((check, index) => (
              <div
                key={`${check.name ?? "check"}-${index}`}
                className="flex items-center gap-2 border-b border-terminal-border py-1 text-xs"
              >
                <StatusDot status={check.ok ?? check.status} />
                <span className="min-w-0 flex-1 truncate text-terminal-text">
                  {check.name ?? `Check ${index + 1}`}
                </span>
                <span className="font-mono uppercase text-terminal-muted">
                  {check.status ?? (check.ok ? "pass" : "fail")}
                </span>
              </div>
            ))}
          </div>
        )}
      </Panel>

      <Panel title="Ops Pulse" action={pulse.data?.status ?? pulse.data?.health ?? "--"}>
        <div className="grid grid-cols-2 gap-2 text-xs">
          <div className="border border-terminal-border p-2">
            <div className="text-terminal-muted">Alerts</div>
            <div className="font-mono text-xl text-terminal-secondary">
              {pulse.data?.alerts?.length ?? 0}
            </div>
          </div>
          <div className="border border-terminal-border p-2">
            <div className="text-terminal-muted">Breakers</div>
            <div className="font-mono text-xl text-terminal-danger">
              {pulse.data?.breakers?.length ?? 0}
            </div>
          </div>
          <div className="border border-terminal-border p-2">
            <div className="text-terminal-muted">Audit Chain</div>
            <div className="font-mono text-xl text-terminal-primary">
              {pulse.data?.audit_chain?.ok === false ? "FAIL" : "OK"}
            </div>
          </div>
          <div className="border border-terminal-border p-2">
            <div className="text-terminal-muted">Workers</div>
            <div className="font-mono text-xl text-terminal-text">
              {pulse.data?.worker_freshness?.length ?? 0}
            </div>
          </div>
        </div>
      </Panel>

      <Panel title="Last 5 Audit Events" className="col-span-2">
        <DataTable<AuditEntry>
          rows={auditRows}
          empty="No audit entries returned"
          getKey={(row, index) => String(row.id ?? index)}
          columns={[
            { key: "ts", header: "TS", render: (row) => formatDate(row.ts ?? row.timestamp) },
            { key: "actor", header: "Actor", render: (row) => row.actor ?? "--" },
            {
              key: "action",
              header: "Action",
              render: (row) => row.action ?? row.category ?? "--"
            },
            { key: "entity", header: "Entity", render: (row) => row.entity_id ?? "--" }
          ]}
        />
      </Panel>

      <Panel title="Active Timers Next Fire">
        <DataTable<TimerRow>
          rows={timerRows}
          empty="No active timers returned"
          getKey={(row, index) => `${row.name ?? index}`}
          columns={[
            { key: "name", header: "Timer", render: (row) => row.name ?? row.unit ?? "--" },
            { key: "next", header: "Next", render: (row) => formatDate(row.next_fire_at) },
            {
              key: "state",
              header: "State",
              render: (row) => row.state ?? (row.active ? "active" : "idle")
            }
          ]}
        />
      </Panel>
    </div>
  );
}
