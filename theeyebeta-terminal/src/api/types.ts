export type Role = "READ_ONLY" | "COMPLIANCE" | "ANALYST" | "OPERATOR" | "MASTER_ADMIN";

export type LoginResponse = {
  access_token?: string;
  token_type?: string;
  expires_in?: number;
  role?: Role;
  username?: string;
  mfa_required?: boolean;
  mfa_token?: string;
  enrollment_required?: boolean;
  enrollment_token?: string;
};

export type CurrentUserResponse = {
  username: string;
  role: Role;
};

export type RefreshResponse = {
  access_token: string;
  expires_in: number;
  role: Role;
  username?: string;
};

export type ServiceRow = {
  name?: string;
  unit?: string;
  state?: string;
  health?: string;
  uptime_seconds?: number;
  last_seen?: string;
  detail?: string;
};

export type ServiceStatusResponse = {
  services?: ServiceRow[];
};

export type PreliveCheck = {
  name?: string;
  status?: string;
  ok?: boolean;
  severity?: string;
  detail?: string;
  checked_at?: string;
};

export type PreliveResponse = {
  overall?: string;
  run_at?: string;
  stale?: boolean;
  checks?: PreliveCheck[];
};

export type AuditEntry = {
  id?: string | number;
  ts?: string;
  timestamp?: string;
  actor?: string;
  action?: string;
  category?: string;
  entity_id?: string;
  detail?: unknown;
  metadata?: unknown;
};

export type AuditLogPageResponse = {
  entries?: AuditEntry[];
  next_cursor?: string | null;
};

export type TimerRow = {
  name?: string;
  unit?: string;
  active?: boolean;
  next_fire_at?: string;
  last_fire_at?: string;
  last_exit_code?: number | null;
  state?: string;
};

export type TimersListResponse = {
  timers?: TimerRow[];
};

export type OpsPulseResponse = {
  status?: string;
  health?: string;
  breakers?: unknown[];
  alerts?: unknown[];
  worker_freshness?: unknown[];
  prelive?: PreliveResponse;
  timers?: TimerRow[];
  services?: ServiceRow[];
  audit_chain?: { ok?: boolean; rows_checked?: number };
};

export type WsEvent = {
  event_id?: string;
  type: string;
  ts?: string;
  severity?: "info" | "warn" | "critical" | string;
  source?: string;
  actor?: string;
  correlation_id?: string;
  payload?: unknown;
};
