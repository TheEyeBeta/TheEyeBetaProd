import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { adminGet } from "../api/http";
import { formatDate } from "../api/normalizers";
import type { AuditEntry, AuditLogPageResponse } from "../api/types";
import { ActionButton } from "../components/ActionButton";
import { DataTable } from "../components/DataTable";
import { EmptyState } from "../components/EmptyState";
import { Panel } from "../components/Panel";

type VerifyResponse = {
  ok?: boolean;
  mismatch_at_id?: string | number | null;
  rows_checked?: number;
  detail?: string;
};

function isoHoursAgo(hours: number) {
  return new Date(Date.now() - hours * 60 * 60 * 1000).toISOString();
}

export function AuditPanel() {
  const [cursor, setCursor] = useState<string | undefined>();
  const [selected, setSelected] = useState<AuditEntry | null>(null);
  const [verifyWindow, setVerifyWindow] = useState({
    from: isoHoursAgo(24),
    to: new Date().toISOString()
  });
  const [verifyRun, setVerifyRun] = useState(0);

  const audit = useQuery({
    queryKey: ["admin", "audit-log", cursor],
    queryFn: () => adminGet<AuditLogPageResponse>("/admin/audit/log", { limit: 50, cursor }),
    refetchInterval: 10000
  });

  const verify = useQuery({
    queryKey: ["admin", "audit-verify", verifyRun],
    queryFn: () => adminGet<VerifyResponse>("/admin/audit/verify", verifyWindow),
    enabled: verifyRun > 0
  });

  const rows = audit.data?.entries ?? [];
  const selectedJson = useMemo(() => JSON.stringify(selected ?? {}, null, 2), [selected]);

  return (
    <div className="grid h-full grid-cols-[1.35fr_0.9fr] gap-2">
      <Panel
        title="Audit Log"
        action={
          <div className="flex gap-2">
            <ActionButton
              disabled={!audit.data?.next_cursor}
              onClick={() => setCursor(audit.data?.next_cursor ?? undefined)}
            >
              Next
            </ActionButton>
            <ActionButton variant="secondary" onClick={() => setCursor(undefined)}>
              Reset
            </ActionButton>
          </div>
        }
      >
        <DataTable<AuditEntry>
          rows={rows}
          empty="No audit events returned"
          getKey={(row, index) => String(row.id ?? index)}
          columns={[
            { key: "ts", header: "TS", render: (row) => formatDate(row.ts ?? row.timestamp) },
            { key: "actor", header: "Actor", render: (row) => row.actor ?? "--" },
            {
              key: "action",
              header: "Action",
              render: (row) => row.action ?? row.category ?? "--"
            },
            { key: "entity", header: "Entity", render: (row) => row.entity_id ?? "--" },
            {
              key: "inspect",
              header: "Inspect",
              render: (row) => (
                <button className="text-terminal-primary" onClick={() => setSelected(row)}>
                  OPEN
                </button>
              )
            }
          ]}
        />
      </Panel>

      <div className="grid min-h-0 grid-rows-[240px_1fr] gap-2">
        <Panel title="Audit Verify">
          <div className="space-y-2 text-xs">
            <label className="block uppercase text-terminal-muted">
              From
              <input
                value={verifyWindow.from}
                onChange={(event) => setVerifyWindow({ ...verifyWindow, from: event.target.value })}
                className="mt-1 h-7 w-full border border-terminal-border bg-terminal-bg px-2 font-mono text-terminal-text"
              />
            </label>
            <label className="block uppercase text-terminal-muted">
              To
              <input
                value={verifyWindow.to}
                onChange={(event) => setVerifyWindow({ ...verifyWindow, to: event.target.value })}
                className="mt-1 h-7 w-full border border-terminal-border bg-terminal-bg px-2 font-mono text-terminal-text"
              />
            </label>
            <ActionButton variant="secondary" onClick={() => setVerifyRun((value) => value + 1)}>
              Verify
            </ActionButton>
            {verify.data ? (
              <div
                className={`border p-2 ${verify.data.ok === false ? "border-terminal-danger text-terminal-danger" : "border-terminal-primary text-terminal-primary"}`}
              >
                {verify.data.ok === false ? "CHAIN MISMATCH" : "CHAIN OK"} /{" "}
                {verify.data.rows_checked ?? 0} rows
              </div>
            ) : null}
          </div>
        </Panel>

        <Panel title="Selected Audit Event">
          {selected ? (
            <pre className="whitespace-pre-wrap break-words font-mono text-xs text-terminal-text">
              {selectedJson}
            </pre>
          ) : (
            <EmptyState label="Select an audit event to inspect inputs, outputs, actor, and metadata" />
          )}
        </Panel>
      </div>
    </div>
  );
}
