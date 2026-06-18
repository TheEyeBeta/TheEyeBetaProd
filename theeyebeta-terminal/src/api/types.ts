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

export type MacroObservation = {
  code?: string;
  name?: string;
  date?: string;
  value?: number | string | null;
  source?: string;
  units?: string;
};

export type MacroLatestResponse = {
  count?: number;
  observations?: MacroObservation[];
};

export type MacroSeriesListItem = {
  code?: string;
  name?: string;
  category?: string;
  units?: string;
  source?: string;
  frequency?: string;
};

export type MacroSeriesListResponse = {
  count?: number;
  series?: MacroSeriesListItem[];
};

export type MacroSeriesDetailResponse = MacroSeriesListItem & {
  observations?: MacroObservation[];
};

export type MacroRegimeResponse = Record<string, unknown>;

export type PendingOrder = {
  id?: string;
  order_id?: string;
  ticker?: string;
  symbol?: string;
  side?: string;
  quantity?: number;
  qty?: number;
  order_type?: string;
  status?: string;
  created_at?: string;
  proposed_at?: string;
  metadata?: unknown;
};

export type PendingOrdersResponse = {
  orders?: PendingOrder[];
  total?: number;
};

export type PositionRow = Record<string, unknown>;

export type SignalRow = {
  id?: string;
  ticker?: string;
  symbol?: string;
  strategy_name?: string;
  strategy?: string;
  signal?: string;
  side?: string;
  confidence?: number;
  score?: number;
  entry?: number;
  target?: number;
  stop?: number;
  created_at?: string;
  timestamp?: string;
};

export type SignalsLatestResponse = {
  signals?: SignalRow[];
};

export type WorkerRun = {
  id?: string | number;
  worker?: string;
  worker_name?: string;
  status?: string;
  started_at?: string;
  finished_at?: string;
  exit_code?: number | null;
  stdout_tail?: string;
  stderr_tail?: string;
};

export type WorkerRunsResponse = {
  runs?: WorkerRun[];
  total?: number;
};

export type DataTableRow = {
  name?: string;
  table_type?: string;
  row_count_estimate?: number;
  basic_access?: boolean;
};

export type DataTablesResponse = {
  tables?: DataTableRow[];
};
