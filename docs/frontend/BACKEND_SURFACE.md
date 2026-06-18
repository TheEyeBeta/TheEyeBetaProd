# TheEyeBeta Frontend Backend Surface

Source of truth for frontend builds. Generated/verified on 2026-06-18.

Primary surfaces:

- DataAPI: external API in sibling repo `/home/the-eye-beta/TheEyeBeta2025/TheEyeBetaDataAPI`, live service `theeyebeta-dataapi`, port `7000`.
- Admin service: this repo `services/admin_service`, port `7200`.
- Full live DataAPI OpenAPI copied verbatim to `docs/frontend/openapi.json`.

Important: `services/api` in this repo is a placeholder. The real DataAPI code lives in the sibling `TheEyeBetaDataAPI` repo.

## Auth Summary

### DataAPI

DataAPI accepts `Authorization: Bearer <token>` for protected endpoints. A bearer token may be:

- Service JWT from `POST /api/v1/auth/service-token` using HTTP Basic client credentials.
- User JWT issued by an external identity provider/JWKS path.
- Personal user API key shaped `teb_uk_<16hex>_<secret>`.
- Optional service mTLS headers when enabled.

Scopes:

- `market:read`: market data, macro, news, references, ticker details, price history, corporate actions.
- `symbols:read`: symbol search.
- `analytics:read`: analytics snapshots, fundamentals, financials, indicators.
- `advisor:read`: advisor context and chat.
- `signals:read`: latest signals.
- `portfolio:read`: portfolio state.
- `admin:read` or `admin:*`: DataAPI admin read endpoints.

### Admin Service

Admin service uses JWT RS256 from `POST /admin/auth/login`. Refresh token is stored as an httpOnly cookie and rotated by `POST /admin/auth/refresh`.

Roles, weakest to strongest:

- `READ_ONLY`
- `COMPLIANCE`
- `ANALYST`
- `OPERATOR`
- `MASTER_ADMIN`

`MASTER_ADMIN` is the system-owner role. Dangerous admin actions still require confirmations, reasons, consequence acknowledgement, and audit rows where implemented.

## 1. All API Endpoints

Legend:

- `READ`: read-only.
- `WRITE`: creates compute/chat/query side effects but not operator control.
- `CONTROL`: operational control or mutation.
- `ADMIN`: admin/security sensitive.
- `WS`: real-time equivalent exists only when `Yes`.

### DataAPI Endpoints

| Method | Path | Auth required | Request shape | Response shape/key fields | WS | Tag |
|---|---|---|---|---|---|---|
| GET | `/` | No | none | `object`: `name`, `version`, `status` | No | READ |
| GET | `/health` | No | none | `HealthResponse`: `status`, `database`, `redis` | No | READ |
| POST | `/api/v1/auth/service-token` | HTTP Basic service credentials | body `ServiceTokenRequest`: `requested_scopes[]` | `ServiceTokenResponse`: `access_token`, `token_type`, `expires_minutes`, `scopes` | No | ADMIN |
| GET | `/api/v1/context` | `advisor:read` | query `ticker?`, `ticker_limit?`, `news_limit?` | `AdvisorContextResponse`: `tickers`, `news`, `ticker_snapshot` | No | READ |
| GET | `/api/v1/advisor/context` | `advisor:read` | same as `/api/v1/context` | `AdvisorContextResponse`: `tickers`, `news`, `ticker_snapshot` | No | READ |
| POST | `/api/v1/chat` | `advisor:read` | body `ChatRequest`: `question`, `ticker?` | `ChatResponse`: `answer`, `used_ticker`, `context_rows` | No | WRITE |
| POST | `/api/v1/advisor/chat` | `advisor:read` | body `ChatRequest`: `question`, `ticker?` | `ChatResponse`: `answer`, `used_ticker`, `context_rows` | No | WRITE |
| GET | `/api/v1/market-data/quotes` | `market:read` | query `symbols` CSV/string | `MarketQuotesResponse`: `quotes` | No | READ |
| GET | `/api/v1/symbols/search` | `symbols:read` | query `q`, `limit?` | `SymbolSearchResponse`: `results` | No | READ |
| GET | `/api/v1/analytics/snapshots/{ticker}` | `analytics:read` | path `ticker` | `AnalyticsSnapshotResponse`: `snapshot` | No | READ |
| GET | `/api/v1/signals/latest` | `signals:read` | query `ticker?`, `limit?` | `SignalsLatestResponse`: `signals` | No | READ |
| GET | `/api/v1/portfolio/state` | `portfolio:read` | query `owner_subject?`, `position_limit?` | `PortfolioStateResponse`: `owner_subject`, `valuation`, `positions` | No | READ |
| GET | `/api/v1/tickers/{ticker}` | `market:read` | path `ticker` | `TickerDetailResponse`: `ticker`, `company_name`, `asset_type`, `country_code`, `currency_code`, `sector_id`, `industry_id`, `website`, `description` | No | READ |
| GET | `/api/v1/tickers/{ticker}/price-history` | `market:read` | path `ticker`; query `start?`, `end?`, `limit?` | `PriceHistoryResponse`: `ticker`, `prices[]` (`date`, OHLCV, `adj_close`, `vwap`) | No | READ |
| GET | `/api/v1/tickers/{ticker}/corporate-actions` | `market:read` | path `ticker`; query `limit?` | `CorporateActionsResponse`: `ticker`, `actions[]` (`action_date`, `action_type`, split/dividend fields) | No | READ |
| GET | `/api/v1/tickers/{ticker}/fundamentals` | `analytics:read` | path `ticker` | `CompanyFundamentalsResponse`: sector/industry, employee, HQ, market-cap/EV/share fields | No | READ |
| GET | `/api/v1/financials/{ticker}/income` | `analytics:read` | path `ticker`; query `limit?` | `IncomeStatementsResponse`: `ticker`, `statements[]` (`period_end`, revenue, EBIT/EBITDA, net income, EPS) | No | READ |
| GET | `/api/v1/financials/{ticker}/balance` | `analytics:read` | path `ticker`; query `limit?` | `BalanceSheetsResponse`: `ticker`, `statements[]` (`period_end`, assets, liabilities, equity, debt, cash) | No | READ |
| GET | `/api/v1/financials/{ticker}/cashflow` | `analytics:read` | path `ticker`; query `limit?` | `CashFlowsResponse`: `ticker`, `statements[]` (`ocf`, `capex`, `fcf`, working-capital fields) | No | READ |
| GET | `/api/v1/financials/{ticker}/quality` | `analytics:read` | path `ticker`; query `limit?` | `QualityMetricsResponse`: `ticker`, `metrics[]` (`roic`, `roe`, `roa`, `wacc`, margin/turnover fields) | No | READ |
| GET | `/api/v1/indicators/{ticker}/technical` | `analytics:read` | path `ticker`; query `start?`, `end?`, `limit?` | `TechnicalIndicatorsResponse`: `ticker`, `indicators[]` (SMA/EMA/RSI/MACD fields) | No | READ |
| GET | `/api/v1/indicators/{ticker}/risk` | `analytics:read` | path `ticker`; query `start?`, `end?`, `limit?` | `RiskIndicatorsResponse`: `ticker`, `indicators[]` (`atr_14`, volatility, beta, drawdown, Sharpe/Sortino) | No | READ |
| GET | `/api/v1/indicators/{ticker}/valuation` | `analytics:read` | path `ticker`; query `start?`, `end?`, `limit?` | `ValuationIndicatorsResponse`: `ticker`, `indicators[]` (`market_cap`, `enterprise_value`, PE/PS/PB/EV ratios) | No | READ |
| GET | `/api/v1/indicators/{ticker}/returns` | `analytics:read` | path `ticker`; query `start?`, `end?`, `limit?` | `ReturnsSnapshotResponse`: `ticker`, `returns[]` (`ret_1w`, `ret_1m`, `ret_3m`, YTD/1Y fields) | No | READ |
| GET | `/api/v1/news/market` | `market:read` | query `limit?` | `MarketNewsResponse`: `news[]` (`headline`, `source`, `category`, `published_at`) | No | READ |
| GET | `/api/v1/news/ticker/{ticker}` | `market:read` | path `ticker`; query `limit?` | `TickerNewsResponse`: `ticker`, `news[]` (`title`, `url`, `summary`, sentiment fields) | No | READ |
| GET | `/v1/macro/series` | `market:read` | query `category?` | `MacroSeriesListResponse`: `count`, `series[]` | No | READ |
| GET | `/v1/macro/latest` | `market:read` | query `codes?` CSV/string | `MacroLatestResponse`: `count`, `observations[]` (`code`, `date`, `value`, `source`) | No | READ |
| GET | `/v1/macro/regime` | `market:read` | none | `MacroRegimeResponse`: rates, 2s10s, VIX/DXY/HY OAS, regime labels | No | READ |
| GET | `/v1/macro/series/{code}` | `market:read` | path `code`; query `start?`, `end?`, `limit?` | `MacroSeriesDetailResponse`: metadata + `observations[]` | No | READ |
| GET | `/api/v1/reference/countries` | `market:read` | none | `CountriesResponse`: `countries[]` | No | READ |
| GET | `/api/v1/reference/currencies` | `market:read` | none | `CurrenciesResponse`: `currencies[]` | No | READ |
| GET | `/api/v1/reference/exchanges` | `market:read` | none | `ExchangesResponse`: `exchanges[]` | No | READ |
| GET | `/api/v1/reference/sectors` | `market:read` | none | `SectorsResponse`: `sectors[]` | No | READ |
| GET | `/api/v1/reference/industries` | `market:read` | query `sector_id?` | `IndustriesResponse`: `industries[]` | No | READ |
| GET | `/api/v1/reference/calendar` | `market:read` | query `start?`, `end?`, `limit?` | `TradingCalendarResponse`: `days[]` (`calendar_date`, `is_trading_day`, holiday fields) | No | READ |
| GET | `/api/v1/data/tables` | Bearer token; any read scope, table filtering applies | none | `DataTablesResponse`: `tables[]` (`name`, `table_type`, `row_count_estimate`, `basic_access`) | No | ADMIN |
| GET | `/api/v1/data/tables/{table}/columns` | Bearer token; table-level authorization | path `table` | `DataColumnsResponse`: `table`, `columns[]` | No | ADMIN |
| GET | `/api/v1/data/tables/{table}/rows` | Bearer token; table-level authorization | path `table`; query `limit?`, `offset?`, `order_by?`, `order_dir?`, `filter[]?`, `symbol?`, `date_column?`, `start?`, `end?` | `DataRowsResponse`: `table`, `limit`, `offset`, `row_count`, `rows[]` | No | ADMIN |
| GET | `/api/v1/admin/audit-events` | `admin:read` | query `limit?`, `category?` | `AdminAuditEventsResponse`: `events[]` | No | ADMIN |
| GET | `/api/v1/admin/dashboard` | No server-side auth; client supplies token in page | none | HTML string | No | ADMIN |
| GET | `/api/v1/admin/dashboard-data` | `admin:read` | none | object dashboard payload | No | ADMIN |
| GET | `/api/v1/admin/named-query` | `admin:read` | query `query_name`, `limit?` | object rows/result | No | ADMIN |
| GET | `/api/v1/admin/queries` | `admin:read` | none | object/list of named queries | No | ADMIN |
| GET | `/api/v1/admin/etl-jobs` | `admin:read` | none | `EtlJobStatesResponse`: `jobs[]` | No | ADMIN |
| GET | `/api/v1/admin/engine-status` | `admin:read` | none | `EngineStatusResponse`: `entries[]` | No | ADMIN |
| GET | `/api/v1/admin/worker-heartbeats` | `admin:read` | none | `WorkerHeartbeatsResponse`: `workers[]` | No | ADMIN |
| GET | `/api/v1/admin/price-ticks/{ticker}` | `admin:read` | path `ticker`; query `limit?` | `PriceTicksResponse`: `ticker`, `ticks[]` | No | ADMIN |

### Admin-Service Endpoints

| Method | Path | Auth required | Request shape | Response shape/key fields | WS | Tag |
|---|---|---|---|---|---|---|
| GET | `/admin/health` | No | none | object: `status`, `service` | No | READ |
| GET | `/metrics` | No | none | Prometheus text | No | READ |
| POST | `/admin/auth/login` | No | body `LoginRequest`: `username`, `password` | `LoginResponse`: tokens or `mfa_required`, `mfa_token`, enrollment flags | No | ADMIN |
| POST | `/admin/auth/refresh` | httpOnly refresh cookie | none | `RefreshResponse`: `access_token`, `expires_in`, `role` | No | ADMIN |
| POST | `/admin/auth/logout` | Bearer access JWT | none | 204 | No | ADMIN |
| POST | `/admin/auth/logout/all` | Bearer access JWT | none | 204 | No | ADMIN |
| GET | `/admin/auth/me` | Bearer access JWT | none | `CurrentUserResponse`: `username`, `role` | No | READ |
| GET | `/admin/auth/sessions` | Bearer access JWT | none | `SessionsListResponse`: sessions with `session_id`, issued/used/ip/user-agent | No | READ |
| DELETE | `/admin/auth/sessions/{session_id}` | Bearer access JWT | path `session_id` | 204 | No | CONTROL |
| POST | `/admin/auth/mfa/enroll` | Enrollment token / authenticated setup | body `MfaEnrollRequest`: `enrollment_token?` | `MfaEnrollResponse`: `secret`, `provisioning_uri`, `backup_codes` | No | ADMIN |
| POST | `/admin/auth/mfa/confirm` | MFA enrollment flow | body `MfaConfirmRequest`: `totp_code`, `enrollment_token?` | 204 | No | ADMIN |
| POST | `/admin/auth/mfa/verify` | `mfa_token` from login | body `MfaVerifyRequest`: `mfa_token`, `totp_code` | `TokenResponse`: access token + role | No | ADMIN |
| POST | `/admin/auth/mfa/backup` | `mfa_token` from login | body `MfaBackupRequest`: `mfa_token`, `backup_code` | `TokenResponse`: access token + role | No | ADMIN |
| GET | `/admin/ops/pulse` | `READ_ONLY+` | none | `OpsPulseResponse`: health, breakers, alerts, worker freshness, prelive, timers, services, audit chain | Yes | READ |
| GET | `/admin/master-admin/control-matrix` | `MASTER_ADMIN` | none | `MasterAdminControlMatrixResponse`: controls, gaps, dangerous action requirements | No | ADMIN |
| GET | `/admin/orders/pending` | Bearer JWT | none | `PendingOrdersResponse`: `orders[]`, `total` | Yes | READ |
| GET | `/admin/orders/{order_id}` | Bearer JWT | path `order_id` | `OrderDetailResponse`: order fields and instrument summary | Yes | READ |
| POST | `/admin/orders/{order_id}/approve` | `OPERATOR+` | path `order_id`; body `ApproveOrderRequest`: `note?` | `ApproveOrderResponse`: `id`, `status`, `approved_by`, `approved_at` | Yes | CONTROL |
| POST | `/admin/orders/{order_id}/reject` | `OPERATOR+` | path `order_id`; body `RejectOrderRequest`: `rejection_reason` | `RejectOrderResponse`: `id`, `status`, `metadata` | No | CONTROL |
| GET | `/admin/audit/log` | Bearer JWT | query `entity_id?`, `actor?`, `since?`, `limit?`, `cursor?` | `AuditLogPageResponse`: `entries[]`, `next_cursor` | Yes | READ |
| GET | `/admin/audit/verify` | Bearer JWT | query `from`, `to` | `AuditVerifyResponse`: `ok`, `mismatch_at_id`, `rows_checked`, `detail` | No | CONTROL |
| GET | `/admin/audit/chain/verify` | Bearer JWT | none | `AuditVerifyResponse` | No | CONTROL |
| GET | `/admin/audit/checkpoints` | Bearer JWT | none | `AuditCheckpointsResponse`: checkpoint rows | No | READ |
| GET | `/admin/agents` | Bearer JWT | none | `AgentsListResponse`: `agents[]` with department/role/run stats | No | READ |
| GET | `/admin/agents/{agent_id}/runs` | Bearer JWT | path `agent_id`; query `limit?` | `AgentRunsResponse`: recent runs | No | READ |
| GET | `/admin/agents/{agent_id}/constitution` | Bearer JWT | path `agent_id` | `AgentConstitutionResponse`: path + markdown content | No | READ |
| POST | `/admin/agents/{agent_id}/run` | `OPERATOR+` | path `agent_id`; body `RunAgentRequest`: `snapshot_id`, `kind`, `agent_messages?` | `RunAgentResponse`: `run_id`, `snapshot_id`, `kind` | No | CONTROL |
| GET | `/admin/guard/violations` | Bearer JWT | query `agent_id?`, `severity?`, `unresolved_only?`, `limit?`, `cursor?` | `GuardViolationsResponse`: violations and cursor | Yes | READ |
| POST | `/admin/guard/violations/{violation_id}/resolve` | `OPERATOR+` | path `violation_id`; body `ResolveGuardViolationRequest`: `note` | `ResolveGuardViolationResponse`: resolved fields | No | CONTROL |
| GET | `/admin/services/status` | Bearer JWT | none | `ServiceStatusResponse`: services with name/unit/state/health/uptime | No | READ |
| POST | `/admin/services/{name}/restart` | `OPERATOR+` | path `name`; body `RestartServiceRequest`: `reason?`, `timeout_seconds` | `RestartServiceResponse`: name, unit/container_id, restarted, state | No | CONTROL |
| GET | `/admin/backtest` | Bearer JWT | query `limit?` | `BacktestListResponse`: runs | No | READ |
| POST | `/admin/backtest` | `OPERATOR+` | body `StartBacktestRequest`: strategy/date/universe/mode/config | `StartBacktestResponse`: `backtest_run_id`, `status` | No | CONTROL |
| GET | `/admin/backtest/{backtest_id}/results` | Bearer JWT | path `backtest_id` | `BacktestResultsResponse`: status, metrics, artifact URI | No | READ |
| GET | `/admin/costs/daily` | Bearer JWT | query `days?` | `DailyCostsResponse`: entries and total cost | No | READ |
| GET | `/admin/costs/by-agent` | Bearer JWT | query `month` | `CostsByAgentResponse`: agent cost rows and totals | No | READ |
| POST | `/admin/sql/query` | `ANALYST+` | body `SqlQueryRequest`: `statement`, `parameters[]?` | `SqlQueryResponse`: columns, rows, row_count, truncated, elapsed_ms | No | READ |
| POST | `/admin/sql/execute` | `MASTER_ADMIN`; headers `X-Confirm`, `X-Idempotency-Key` | body `SqlExecuteRequest`: `statement`, `parameters[]?` | `SqlExecuteResponse`: command_tag, rows_affected, elapsed_ms, idempotency_key | No | ADMIN |
| GET | `/admin/proposals` | Bearer JWT | query status/category/proposed_by/target/limit/cursor | `ProposalsListResponse`: proposals and cursor | No | READ |
| GET | `/admin/proposals/{proposal_id}` | Bearer JWT | path `proposal_id` | `ProposalDetail` | No | READ |
| POST | `/admin/proposals/{proposal_id}/approve` | `OPERATOR+` | body `ApproveProposalRequest`: review notes, optional validation backtest config | `ApproveProposalResponse`: reviewed fields, validation_backtest_id | No | CONTROL |
| POST | `/admin/proposals/{proposal_id}/reject` | `OPERATOR+` | body `RejectProposalRequest`: `review_notes` | `RejectProposalResponse` | No | CONTROL |
| GET | `/admin/workers` | `READ_ONLY+` | none | `WorkersListResponse`: registry entries | No | READ |
| GET | `/admin/workers/runs` | `READ_ONLY+` | query worker/status/date/limit/offset | `WorkerRunsResponse`: runs and total | No | READ |
| POST | `/admin/workers/{name}/run` | `OPERATOR+` | path `name`; body `WorkerRunRequest`: `dry_run`, `force`, `args`, `reason` | `WorkerRunResponse`: run id, exit code, stdout/stderr tails | No | CONTROL |
| GET | `/admin/trask/dashboard` | `READ_ONLY+` | none | `TraskDashboardResponse`: component and breaker state | No | READ |
| POST | `/admin/trask/breakers/{breaker_id}/reset` | `MASTER_ADMIN` | body `BreakerResetRequest`: `reason`, `consequences_acknowledged`, `override` | `BreakerResetResponse` | No | CONTROL |
| GET | `/admin/alerts` | `READ_ONLY+` | query severity/status/ack/source/date/limit/offset | `AlertsListResponse`: alerts and total | Yes | READ |
| POST | `/admin/alerts/{alert_id}/ack` | `OPERATOR+` | body `AlertAckRequest`: `note?` | `AlertAckResponse`: ack fields | No | CONTROL |
| GET | `/admin/prelive` | `READ_ONLY+` | query `run?` boolean | `PreliveResponse`: overall, run_at, stale flag, checks | No | CONTROL |
| GET | `/admin/trading/live-approval/token` | `MASTER_ADMIN` | none | object: `confirmation_token`, `expires_in` | No | ADMIN |
| POST | `/admin/trading/live-approval` | `MASTER_ADMIN` | body `LiveApprovalRequest`: enable, reason, consequences_acknowledged, confirmation_token | `LiveApprovalResponse` | Yes | CONTROL |
| POST | `/admin/trading/emergency-halt` | `MASTER_ADMIN` | body `EmergencyHaltRequest`: reason, consequences_acknowledged | `EmergencyHaltResponse`: halted, timestamp, NATS/Redis flags | Yes | CONTROL |
| GET | `/admin/timers` | `READ_ONLY+` | none | `TimersListResponse`: timer status rows | No | READ |
| POST | `/admin/timers/{name}/trigger` | `OPERATOR+` | body `TimerTriggerRequest`: `reason` | `TimerTriggerResponse`: name, unit, triggered_at, exit_code | No | CONTROL |
| GET | `/admin/briefings` | Bearer JWT | query `limit?` | `BriefingsListResponse`: briefings and total | No | READ |
| GET | `/admin/risk/metrics` | `ANALYST+` | none | object: recent risk metrics | No | READ |
| POST | `/admin/risk/compute` | `OPERATOR+` | none | object: compute trigger result | No | CONTROL |
| GET | `/admin/compliance/checks` | `COMPLIANCE+` | none | object: checks rows, total | No | READ |
| GET | `/admin/oms/reconciliation` | `OPERATOR+` | none | object: OMS health and open reconciliation alerts | Yes | READ |
| POST | `/admin/oms/reconciliation/resolve` | `MASTER_ADMIN` | body `ReconciliationResolveRequest`: `reason` | object from OMS resolve + audit | No | CONTROL |
| GET | `/admin/broker/status` | `ANALYST+` | none | object from broker adapter health | No | READ |
| GET | `/admin/broker/positions` | `ANALYST+` | none | object from broker adapter positions | No | READ |

## 2. WebSocket / Streaming Endpoints

### Admin Service WS

Endpoint: `WS /admin/events/stream`

Auth flow:

1. Connect without query token.
2. Server accepts the socket.
3. Within 10 seconds, client sends first message:

```json
{"type": "auth", "token": "<admin access JWT>"}
```

4. Server validates JWT using admin-service settings.
5. On failure, server closes with WebSocket code `1008`.
6. On internal broadcaster missing, server closes with `1011`.

Message envelope:

```json
{
  "event_id": "uuid",
  "type": "order.proposed | order.approved | broker.fill | audit.event | alert.created | trading.halt | ping",
  "ts": "ISO-8601 UTC timestamp",
  "severity": "info | warn | critical",
  "source": "master_orchestrator | admin_service | broker_adapter | audit_service | guard_service | oms | system",
  "actor": "system or actor string",
  "correlation_id": "uuid/string",
  "payload": {}
}
```

NATS subjects bridged:

- `orders.proposed.>` -> `order.proposed`
- `orders.approved.>` -> `order.approved`
- `broker.fills.>` -> `broker.fill`
- `audit.events.>` -> `audit.event`
- `agents.violations.escalated.>` -> `alert.created`
- `risk.breaches.reconciliation` -> `alert.created` with `critical`
- `trading.emergency.>` -> `trading.halt`

Heartbeat/reconnect:

- If no event arrives for 30 seconds, server sends `{"type":"ping","ts":"..."}`.
- No resumable cursor exists. Frontend should reconnect with exponential backoff and re-fetch REST state after reconnect.

### DataAPI WS/SSE

No WebSocket or SSE endpoints are present in the live DataAPI OpenAPI or sibling route files.

## 3. Data Domains

| Domain | Primary endpoints | Key UI fields | Update frequency |
|---|---|---|---|
| Prices | DataAPI `/api/v1/market-data/quotes`, `/api/v1/tickers/{ticker}/price-history`, admin `/api/v1/admin/price-ticks/{ticker}` | ticker, last/OHLCV, adj_close, vwap, source, timestamp | Intraday timer during market hours; EOD nightly |
| Macro | DataAPI `/v1/macro/series`, `/v1/macro/latest`, `/v1/macro/regime`, `/v1/macro/series/{code}` | code, name, date, value, units, source, regime labels | Nightly/refresh jobs; on-demand query |
| Signals | DataAPI `/api/v1/signals/latest`; admin `/admin/proposals` | ticker, strategy_name, signal, confidence, entry/target/stop, timestamp | On-demand/latest; agent/proposal driven |
| Positions | DataAPI `/api/v1/portfolio/state`; admin `/admin/broker/positions` | ticker, quantity, avg cost, last price, market value, PnL | Broker/read on-demand; frontend should refresh/poll |
| Orders | Admin `/admin/orders/*`; WS `order.proposed`, `order.approved`, `broker.fill` | id, client_order_id, instrument, side, qty, type, status, timestamps | Real-time via WS plus REST fetch |
| Risk Metrics | Admin `/admin/risk/metrics`, `/admin/risk/compute`; DataAPI indicator risk endpoint for ticker analytics | VaR/CVaR style service fields, ATR, vol, beta, drawdown, Sharpe/Sortino | Risk refresh timer/on-demand compute |
| Audit Log | Admin `/admin/audit/log`, `/admin/audit/verify`, `/admin/audit/checkpoints`; DataAPI `/api/v1/admin/audit-events` | ts, actor, action, entity, payload, verify status | Append-only; WS mirrors `audit.event` |
| Workers | Admin `/admin/workers`, `/admin/workers/runs`, `/admin/workers/{name}/run`; DataAPI `/api/v1/admin/worker-heartbeats` | worker id/name, state, heartbeat, last run, status, errors | Heartbeats/polling; scheduled runs |
| Services Health | Admin `/admin/services/status`, `/admin/ops/pulse`; DataAPI `/health`, admin `/admin/health` | service, unit, state, health, uptime | Poll every 15-60 seconds |
| Admin Users | Admin `/admin/auth/me`, `/admin/auth/sessions`, login/MFA endpoints | username, role, session id, issued/last used, IP, MFA state | On-demand |
| API Keys | DataAPI bearer personal API key verifier only; scripts provision keys | key prefix, scopes, revoked/expired events if exposed via DB | No frontend API for issue/revoke today |
| Fundamentals | DataAPI `/api/v1/tickers/{ticker}/fundamentals`, `/api/v1/financials/{ticker}/*` | sector, industry, market cap, statements, ROIC/quality fields | Nightly/on-demand |
| Corporate Actions | DataAPI `/api/v1/tickers/{ticker}/corporate-actions` | action_date, type, split ratio, dividend amount, notes | Nightly/on-demand |

## 4. Controllable Actions

Actions currently exposed through DataAPI/admin service:

| Action | Endpoint | Role/scope | Notes |
|---|---|---|---|
| Issue service token | DataAPI `POST /api/v1/auth/service-token` | HTTP Basic service credentials | Grants requested subset of client scopes |
| Advisor chat | DataAPI `POST /api/v1/chat`, `/api/v1/advisor/chat` | `advisor:read` | LLM side effect/cost; not an operator control |
| Login | Admin `POST /admin/auth/login` | public + credentials | May return MFA pending/enrollment |
| Refresh token | Admin `POST /admin/auth/refresh` | refresh cookie | Rotates refresh token |
| Logout current/all | Admin `POST /admin/auth/logout`, `/logout/all` | access JWT | Revokes refresh session(s) |
| Revoke admin session | Admin `DELETE /admin/auth/sessions/{session_id}` | access JWT | Revokes one refresh session |
| Enroll/confirm/verify MFA | Admin MFA endpoints | MFA/login flow | Required for protected admin accounts, especially `MASTER_ADMIN` |
| Approve/reject order | Admin `POST /admin/orders/{id}/approve|reject` | `OPERATOR+` | Writes DB, publishes order approval, audit logged |
| Run agent | Admin `POST /admin/agents/{id}/run` | `OPERATOR+` | Proxies agent runtime and audits |
| Resolve guard violation | Admin `POST /admin/guard/violations/{id}/resolve` | `OPERATOR+` | Writes resolution audit |
| Restart service | Admin `POST /admin/services/{name}/restart` | `OPERATOR+` | Whitelisted systemd units only |
| Start backtest | Admin `POST /admin/backtest` | `OPERATOR+` | Starts validation/backtest flow |
| SQL read query | Admin `POST /admin/sql/query` | `ANALYST+` | SELECT/WITH SELECT only |
| SQL write execute | Admin `POST /admin/sql/execute` | `MASTER_ADMIN` | Requires confirm/idempotency headers; dangerous |
| Approve/reject proposal | Admin proposal POST endpoints | `OPERATOR+` | Approval may create validation backtest |
| Trigger manual worker run | Admin `POST /admin/workers/{name}/run` | `OPERATOR+` | Supports dry_run/force/date args |
| Reset Trask breaker | Admin `POST /admin/trask/breakers/{id}/reset` | `MASTER_ADMIN` | Requires consequence acknowledgement |
| Acknowledge alert | Admin `POST /admin/alerts/{id}/ack` | `OPERATOR+` | Audit/status mutation |
| Force prelive check | Admin `GET /admin/prelive?run=true` | `READ_ONLY+` today | Side effect despite GET; frontend should treat as CONTROL |
| Enable/disable live trading | Admin `POST /admin/trading/live-approval` | `MASTER_ADMIN` | Requires token + consequence ack |
| Emergency halt | Admin `POST /admin/trading/emergency-halt` | `MASTER_ADMIN` | Redis + NATS halt signal, audited |
| Trigger systemd timer | Admin `POST /admin/timers/{name}/trigger` | `OPERATOR+` | Whitelisted timers |
| Trigger risk compute | Admin `POST /admin/risk/compute` | `OPERATOR+` | Calls risk metric refresh script/service |
| Resolve OMS reconciliation | Admin `POST /admin/oms/reconciliation/resolve` | `MASTER_ADMIN` | Proxies OMS and audits |

Requested-but-not-exposed actions:

- Place paper order: not exposed by DataAPI/admin. Direct backend exists at broker adapter `POST /v1/orders/market`, but it is outside DataAPI/admin and should not be called by the frontend until proxied/audited.
- Stop worker: no admin endpoint. Only manual run exists.
- Revoke API key: no DataAPI/admin endpoint. DataAPI validates personal keys and scripts can provision/rotate service keys, but frontend revoke requires new API.
- Trigger snapshot build: not exposed by DataAPI/admin. Direct backend exists at snapshot-packager `POST /snapshots/build`; add an admin proxy before frontend use.
- Start/stop service beyond restart: not exposed. Add start/stop/enable/disable endpoints with allowlists.

## 5. Auth Flow

### Browser Admin JWT

1. `POST /admin/auth/login`

```json
{"username": "operator", "password": "secret"}
```

2. Response either returns an access token:

```json
{"access_token": "...", "token_type": "bearer", "expires_in": 900, "role": "OPERATOR", "mfa_required": false}
```

or an MFA state:

```json
{"mfa_required": true, "mfa_token": "..."}
```

or enrollment state:

```json
{"mfa_enrollment_required": true, "enrollment_token": "..."}
```

3. Store access token in browser memory/session storage as currently used by the admin shell. Refresh token is set as httpOnly cookie.
4. Use `Authorization: Bearer <access_token>` on admin REST and first WS auth message.
5. Use `POST /admin/auth/refresh` to rotate refresh cookie and get a new access token.
6. Use `POST /admin/auth/logout` or `/logout/all` to revoke.

### MFA For MASTER_ADMIN

- Enroll with `POST /admin/auth/mfa/enroll` using `MfaEnrollRequest`.
- Confirm with `POST /admin/auth/mfa/confirm` and a valid TOTP code.
- Login completes with `POST /admin/auth/mfa/verify` using `{mfa_token, totp_code}`.
- Backup code fallback uses `POST /admin/auth/mfa/backup`.
- Failed MFA attempts are counted and can lock the user temporarily.

### DataAPI Token

Service clients call:

```http
POST /api/v1/auth/service-token
Authorization: Basic base64(client_id:client_secret)
Content-Type: application/json

{"requested_scopes": ["market:read", "advisor:read"]}
```

The returned `access_token` is used as `Authorization: Bearer ...` on DataAPI routes.

### WS Auth

Admin WS uses first-message auth:

```json
{"type": "auth", "token": "<admin access JWT>"}
```

Do not put tokens in the WS URL.

## 6. OpenAPI

The full live DataAPI `/openapi.json` was copied to:

```text
docs/frontend/openapi.json
```

Fetch command that succeeded:

```bash
curl -fsS --max-time 8 -H "Host: 127.0.0.1" http://127.0.0.1:7000/openapi.json -o docs/frontend/openapi.json
```

Admin-service OpenAPI is not copied here because the user requested the DataAPI OpenAPI file. For admin-service schema details, use `GET http://127.0.0.1:7200/openapi.json` after restarting admin-service, or import `services/admin_service/main.py:create_app()` from source.
