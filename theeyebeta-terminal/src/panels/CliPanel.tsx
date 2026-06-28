import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { adminGet, adminPost, adminPostWithHeaders } from "../api/http";
import { formatDate } from "../api/normalizers";
import type {
  SqlQueryResponse,
  TimerRow,
  TimersListResponse,
  WorkerRegistryEntry,
  WorkersListResponse
} from "../api/types";
import { ActionButton } from "../components/ActionButton";
import { DataTable } from "../components/DataTable";
import { Panel } from "../components/Panel";
import { StatusDot } from "../components/StatusDot";

type CommandKind = "sql-query" | "sql-execute" | "worker-run" | "timer-trigger" | "prelive";

export function CliPanel() {
  const queryClient = useQueryClient();
  const [kind, setKind] = useState<CommandKind>("sql-query");
  const [target, setTarget] = useState("");
  const [statement, setStatement] = useState("SELECT now() AS server_time;");
  const [reason, setReason] = useState("MASTER_ADMIN terminal CLI action");
  const [force, setForce] = useState(false);
  const [dryRun, setDryRun] = useState(true);

  const workers = useQuery({
    queryKey: ["admin", "cli-workers"],
    queryFn: () => adminGet<WorkersListResponse>("/admin/workers"),
    refetchInterval: 30000
  });
  const timers = useQuery({
    queryKey: ["admin", "cli-timers"],
    queryFn: () => adminGet<TimersListResponse>("/admin/timers"),
    refetchInterval: 30000
  });

  const execute = useMutation({
    mutationFn: async () => {
      if (kind === "sql-query") {
        return adminPost<SqlQueryResponse>("/admin/sql/query", { statement, parameters: [] });
      }
      if (kind === "sql-execute") {
        if (!window.confirm("Execute write SQL as MASTER_ADMIN? This is dangerous and audited.")) {
          return { cancelled: true };
        }
        return adminPostWithHeaders(
          "/admin/sql/execute",
          { statement, parameters: [] },
          {
            "X-Confirm": "true",
            "X-Idempotency-Key": window.crypto.randomUUID()
          }
        );
      }
      if (kind === "worker-run") {
        return adminPost(`/admin/workers/${encodeURIComponent(target)}/run`, {
          dry_run: dryRun,
          force,
          args: {},
          reason
        });
      }
      if (kind === "timer-trigger") {
        return adminPost(`/admin/timers/${encodeURIComponent(target)}/trigger`, { reason });
      }
      return adminGet("/admin/prelive", { run: true });
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["admin", "cli-workers"] });
      void queryClient.invalidateQueries({ queryKey: ["admin", "cli-timers"] });
    }
  });

  const needsTarget = kind === "worker-run" || kind === "timer-trigger";
  const result = useMemo(
    () => JSON.stringify(execute.data ?? execute.error ?? {}, null, 2),
    [execute.data, execute.error]
  );

  return (
    <div className="grid h-full grid-cols-[0.9fr_1.1fr_1fr] gap-2">
      <Panel title="Audited Command Console">
        <div className="space-y-3 text-xs">
          <label className="block uppercase text-terminal-muted">
            Command
            <select
              value={kind}
              onChange={(event) => setKind(event.target.value as CommandKind)}
              className="mt-1 h-8 w-full border border-terminal-border bg-terminal-bg px-2 font-mono text-terminal-text outline-none focus:border-terminal-primary"
            >
              <option value="sql-query">SQL read query</option>
              <option value="sql-execute">SQL write execute</option>
              <option value="worker-run">Run worker</option>
              <option value="timer-trigger">Trigger timer</option>
              <option value="prelive">Force prelive check</option>
            </select>
          </label>
          {needsTarget ? (
            <label className="block uppercase text-terminal-muted">
              Target
              <input
                value={target}
                onChange={(event) => setTarget(event.target.value)}
                placeholder={kind === "worker-run" ? "worker alias/name" : "timer name"}
                className="mt-1 h-8 w-full border border-terminal-border bg-terminal-bg px-2 font-mono text-terminal-text outline-none focus:border-terminal-primary"
              />
            </label>
          ) : null}
          {kind.startsWith("sql") ? (
            <label className="block uppercase text-terminal-muted">
              Statement
              <textarea
                value={statement}
                onChange={(event) => setStatement(event.target.value)}
                className="mt-1 h-36 w-full border border-terminal-border bg-terminal-bg p-2 font-mono text-terminal-text outline-none focus:border-terminal-primary"
              />
            </label>
          ) : null}
          {kind === "worker-run" ? (
            <div className="flex gap-3 uppercase text-terminal-muted">
              <label className="flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={dryRun}
                  onChange={(event) => setDryRun(event.target.checked)}
                />
                Dry run
              </label>
              <label className="flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={force}
                  onChange={(event) => setForce(event.target.checked)}
                />
                Force
              </label>
            </div>
          ) : null}
          {!kind.startsWith("sql") ? (
            <label className="block uppercase text-terminal-muted">
              Reason
              <textarea
                value={reason}
                onChange={(event) => setReason(event.target.value)}
                className="mt-1 h-20 w-full border border-terminal-border bg-terminal-bg p-2 font-mono text-terminal-text outline-none focus:border-terminal-primary"
              />
            </label>
          ) : null}
          <ActionButton
            variant={kind === "sql-execute" ? "danger" : "primary"}
            disabled={execute.isPending || (needsTarget && !target)}
            onClick={() => execute.mutate()}
          >
            Execute
          </ActionButton>
          <div className="border border-terminal-border p-2 text-terminal-muted">
            Raw shell is not exposed by the backend. These commands are the audited CLI equivalents
            currently available to MASTER_ADMIN.
          </div>
        </div>
      </Panel>

      <Panel title="Command Result">
        <pre className="whitespace-pre-wrap break-words font-mono text-xs text-terminal-text">
          {result === "{}" ? "No command result yet." : result}
        </pre>
      </Panel>

      <div className="grid min-h-0 grid-rows-[1fr_1fr] gap-2">
        <Panel title="Worker Targets">
          <DataTable<WorkerRegistryEntry>
            rows={workers.data?.workers ?? []}
            empty="No worker targets returned"
            getKey={(row, index) => row.name ?? String(index)}
            columns={[
              { key: "state", header: "", render: (row) => <StatusDot status={row.state} /> },
              {
                key: "name",
                header: "Name",
                render: (row) => (
                  <button
                    className="text-terminal-primary"
                    onClick={() => setTarget(row.alias ?? row.name ?? "")}
                  >
                    {row.name ?? "--"}
                  </button>
                )
              },
              { key: "alias", header: "Alias", render: (row) => row.alias ?? "--" },
              { key: "last", header: "Last", render: (row) => row.last_run_status ?? "--" }
            ]}
          />
        </Panel>
        <Panel title="Timer Targets">
          <DataTable<TimerRow>
            rows={timers.data?.timers ?? []}
            empty="No timer targets returned"
            getKey={(row, index) => row.name ?? String(index)}
            columns={[
              {
                key: "state",
                header: "",
                render: (row) => <StatusDot status={row.status ?? row.state} />
              },
              {
                key: "name",
                header: "Name",
                render: (row) => (
                  <button
                    className="text-terminal-primary"
                    onClick={() => setTarget(row.name ?? "")}
                  >
                    {row.name ?? "--"}
                  </button>
                )
              },
              {
                key: "next",
                header: "Next",
                render: (row) => formatDate(row.next_trigger ?? row.next_fire_at)
              }
            ]}
          />
        </Panel>
      </div>
    </div>
  );
}
