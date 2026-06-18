import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { adminGet, adminPost } from "../api/http";
import { formatDate } from "../api/normalizers";
import type { TimerRow, TimersListResponse, WorkerRun, WorkerRunsResponse } from "../api/types";
import { ActionButton } from "../components/ActionButton";
import { DataTable } from "../components/DataTable";
import { Panel } from "../components/Panel";
import { StatusDot } from "../components/StatusDot";

export function PipelinesPanel() {
  const queryClient = useQueryClient();
  const [reason, setReason] = useState("Manual MASTER_ADMIN terminal trigger");
  const [workerName, setWorkerName] = useState("");

  const timers = useQuery({
    queryKey: ["admin", "pipeline-timers"],
    queryFn: () => adminGet<TimersListResponse>("/admin/timers"),
    refetchInterval: 30000
  });
  const runs = useQuery({
    queryKey: ["admin", "worker-runs"],
    queryFn: () => adminGet<WorkerRunsResponse>("/admin/workers/runs", { limit: 20 }),
    refetchInterval: 10000
  });

  const triggerTimer = useMutation({
    mutationFn: (name: string) =>
      adminPost(`/admin/timers/${encodeURIComponent(name)}/trigger`, { reason }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["admin", "pipeline-timers"] });
      void queryClient.invalidateQueries({ queryKey: ["admin", "worker-runs"] });
    }
  });

  const runWorker = useMutation({
    mutationFn: () =>
      adminPost(`/admin/workers/${encodeURIComponent(workerName)}/run`, {
        dry_run: false,
        force: true,
        args: {},
        reason
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["admin", "worker-runs"] });
    }
  });

  const runRows = runs.data?.runs ?? [];
  const gapRuns = runRows.filter((run) =>
    String(run.worker ?? run.worker_name ?? "")
      .toLowerCase()
      .includes("gap")
  );

  return (
    <div className="grid h-full grid-cols-[1fr_1fr] grid-rows-[1fr_1fr] gap-2">
      <Panel title="Active Timers">
        <DataTable<TimerRow>
          rows={timers.data?.timers ?? []}
          empty="No timers returned"
          getKey={(row, index) => row.name ?? row.unit ?? String(index)}
          columns={[
            {
              key: "state",
              header: "",
              render: (row) => <StatusDot status={row.state ?? row.active} />
            },
            { key: "name", header: "Timer", render: (row) => row.name ?? row.unit ?? "--" },
            { key: "next", header: "Next Fire", render: (row) => formatDate(row.next_fire_at) },
            { key: "last", header: "Last Fire", render: (row) => formatDate(row.last_fire_at) },
            {
              key: "trigger",
              header: "Trigger",
              render: (row) =>
                row.name ? (
                  <ActionButton variant="secondary" onClick={() => triggerTimer.mutate(row.name!)}>
                    Run
                  </ActionButton>
                ) : (
                  "--"
                )
            }
          ]}
        />
      </Panel>

      <Panel title="Manual Pipeline Run">
        <div className="space-y-3 text-xs">
          <label className="block uppercase text-terminal-muted">
            Worker name
            <input
              value={workerName}
              onChange={(event) => setWorkerName(event.target.value)}
              className="mt-1 h-8 w-full border border-terminal-border bg-terminal-bg px-2 font-mono text-terminal-text outline-none focus:border-terminal-primary"
              placeholder="registered-worker-name"
            />
          </label>
          <label className="block uppercase text-terminal-muted">
            Reason
            <textarea
              value={reason}
              onChange={(event) => setReason(event.target.value)}
              className="mt-1 h-24 w-full border border-terminal-border bg-terminal-bg p-2 font-mono text-terminal-text outline-none focus:border-terminal-primary"
            />
          </label>
          <ActionButton
            disabled={!workerName || runWorker.isPending}
            onClick={() => runWorker.mutate()}
          >
            Run Worker
          </ActionButton>
          {runWorker.data ? (
            <pre className="whitespace-pre-wrap border border-terminal-primary p-2 font-mono text-terminal-text">
              {JSON.stringify(runWorker.data, null, 2)}
            </pre>
          ) : null}
        </div>
      </Panel>

      <Panel title="Worker Run History">
        <DataTable<WorkerRun>
          rows={runRows}
          empty="No worker runs returned"
          getKey={(row, index) => String(row.id ?? index)}
          columns={[
            {
              key: "worker",
              header: "Worker",
              render: (row) => row.worker ?? row.worker_name ?? "--"
            },
            { key: "status", header: "Status", render: (row) => row.status ?? "--" },
            { key: "exit", header: "Exit", render: (row) => row.exit_code ?? "--" },
            { key: "started", header: "Started", render: (row) => formatDate(row.started_at) }
          ]}
        />
      </Panel>

      <Panel title="Gap Sentinel Runs">
        <DataTable<WorkerRun>
          rows={gapRuns}
          empty="No GapSentinel worker runs returned"
          getKey={(row, index) => String(row.id ?? index)}
          columns={[
            {
              key: "worker",
              header: "Worker",
              render: (row) => row.worker ?? row.worker_name ?? "--"
            },
            { key: "status", header: "Status", render: (row) => row.status ?? "--" },
            { key: "finished", header: "Finished", render: (row) => formatDate(row.finished_at) },
            { key: "stderr", header: "stderr", render: (row) => row.stderr_tail ?? "--" }
          ]}
        />
      </Panel>
    </div>
  );
}
