import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { adminDelete, adminGet, adminPost } from "../api/http";
import { asArray, formatDate } from "../api/normalizers";
import { ActionButton } from "../components/ActionButton";
import { DataTable } from "../components/DataTable";
import { EmptyState } from "../components/EmptyState";
import { Panel } from "../components/Panel";

type SessionRow = {
  session_id?: string;
  issued_at?: string;
  last_used_at?: string;
  ip?: string;
  user_agent?: string;
};

export function AdminPanel() {
  const queryClient = useQueryClient();
  const [reason, setReason] = useState("MASTER_ADMIN terminal operation");
  const [liveEnable, setLiveEnable] = useState(false);

  const sessions = useQuery({
    queryKey: ["admin", "sessions"],
    queryFn: () => adminGet<unknown>("/admin/auth/sessions"),
    refetchInterval: 30000
  });

  const prelive = useMutation({
    mutationFn: () => adminGet<unknown>("/admin/prelive", { run: true })
  });

  const revokeSession = useMutation({
    mutationFn: (sessionId: string) =>
      adminDelete(`/admin/auth/sessions/${encodeURIComponent(sessionId)}`),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["admin", "sessions"] });
    }
  });

  const liveApproval = useMutation({
    mutationFn: async () => {
      if (
        !window.confirm(
          `Confirm live trading ${liveEnable ? "enable" : "disable"}? Consequences will be audited.`
        )
      ) {
        return { cancelled: true };
      }
      const tokenResponse =
        (await adminGet<{ confirmation_token?: string }>("/admin/trading/live-approval/token")) ??
        {};
      return adminPost("/admin/trading/live-approval", {
        enable: liveEnable,
        reason,
        consequences_acknowledged: true,
        confirmation_token: tokenResponse.confirmation_token
      });
    }
  });

  const halt = useMutation({
    mutationFn: async () => {
      if (
        !window.confirm(
          "Emergency halt will stop trading controls and publish halt flags. Continue?"
        )
      ) {
        return { cancelled: true };
      }
      return adminPost("/admin/trading/emergency-halt", {
        reason,
        consequences_acknowledged: true
      });
    }
  });

  const sessionRows = asArray<SessionRow>(sessions.data, ["sessions"]);

  return (
    <div className="grid h-full grid-cols-[1fr_1fr] grid-rows-[1fr_1fr] gap-2">
      <Panel title="Admin Sessions">
        <DataTable<SessionRow>
          rows={sessionRows}
          empty="No active admin sessions returned"
          getKey={(row, index) => row.session_id ?? String(index)}
          columns={[
            {
              key: "session",
              header: "Session",
              render: (row) => row.session_id?.slice(0, 12) ?? "--"
            },
            { key: "issued", header: "Issued", render: (row) => formatDate(row.issued_at) },
            { key: "last", header: "Last Used", render: (row) => formatDate(row.last_used_at) },
            { key: "ip", header: "IP", render: (row) => row.ip ?? "--" },
            {
              key: "revoke",
              header: "Revoke",
              render: (row) =>
                row.session_id ? (
                  <ActionButton
                    variant="danger"
                    onClick={() => revokeSession.mutate(row.session_id!)}
                  >
                    Kill
                  </ActionButton>
                ) : (
                  "--"
                )
            }
          ]}
        />
      </Panel>

      <Panel title="MASTER_ADMIN Controls">
        <div className="space-y-3 text-xs">
          <label className="block uppercase text-terminal-muted">
            Required reason / audit note
            <textarea
              value={reason}
              onChange={(event) => setReason(event.target.value)}
              className="mt-1 h-20 w-full border border-terminal-border bg-terminal-bg p-2 font-mono text-terminal-text outline-none focus:border-terminal-primary"
            />
          </label>
          <div className="flex flex-wrap gap-2">
            <ActionButton variant="secondary" onClick={() => prelive.mutate()}>
              Force Prelive
            </ActionButton>
            <label className="flex h-7 items-center gap-2 border border-terminal-border px-2 uppercase text-terminal-muted">
              <input
                type="checkbox"
                checked={liveEnable}
                onChange={(event) => setLiveEnable(event.target.checked)}
              />
              Live enable
            </label>
            <ActionButton onClick={() => liveApproval.mutate()}>Live Approval</ActionButton>
            <ActionButton variant="danger" onClick={() => halt.mutate()}>
              Emergency Halt
            </ActionButton>
          </div>
          <div className="border border-terminal-border p-2 text-terminal-muted">
            API key revocation and snapshot build controls are intentionally disabled:
            BACKEND_SURFACE.md exposes no frontend-safe revoke-key or trigger-snapshot endpoint.
            Backend work needed: audited POST/DELETE endpoints with confirmation token, reason,
            rollback/restore metadata, and immutable audit rows.
          </div>
        </div>
      </Panel>

      <Panel title="Action Results">
        {[prelive.data, liveApproval.data, halt.data].some(Boolean) ? (
          <pre className="whitespace-pre-wrap break-words font-mono text-xs text-terminal-text">
            {JSON.stringify(
              { prelive: prelive.data, liveApproval: liveApproval.data, emergencyHalt: halt.data },
              null,
              2
            )}
          </pre>
        ) : (
          <EmptyState label="Run a dangerous or control action to inspect the timestamped response" />
        )}
      </Panel>

      <Panel title="Unsupported Backend Controls">
        <div className="grid grid-cols-2 gap-2 text-xs">
          {[
            ["API Keys", "No /admin/api-keys list/revoke endpoints exposed."],
            ["Snapshot Build", "No frontend trigger endpoint for snapshot construction."],
            ["User Permission Assignment", "No users/roles mutation endpoint exposed."],
            ["Worker Pause/Resume", "Workers expose run, not pause/resume/stop controls."]
          ].map(([title, detail]) => (
            <div key={title} className="border border-terminal-border p-2">
              <div className="uppercase text-terminal-secondary">{title}</div>
              <div className="mt-2 text-terminal-muted">{detail}</div>
            </div>
          ))}
        </div>
      </Panel>
    </div>
  );
}
