# Services status

Snapshot from the 2026-06-15 remediation pass. These services under `services/` have FastAPI/gRPC
apps but **no running systemd unit** — they are scaffolded, not deployed. They are intentionally
**not started** (starting an unfinished service just creates a failing unit). Each entrypoint
carries a matching `# STATUS:` header.

**Deployed today (for contrast):** `admin_service` (system unit, `:7200`), the Data API
(`theeyebeta-dataapi`, user unit, `:7000`, in the sibling `TheEyeBetaDataAPI` repo), the LiteLLM
proxy (`theeyebeta-litellm`, `:4000`), and the timer-driven workers (intraday/macro/macro-refresh/
massive/sector/market-cap/daily-pipeline/gap-sentinel/backup/news).

Effort is a rough order-of-magnitude estimate (S ≈ <1d, M ≈ 1–3d, L ≈ >3d), not a commitment.

| Service | Purpose | Blocker | Effort |
|---|---|---|---|
| `agent_runtime` | AI agent runtime (FastAPI :8004) | Deployed via `theeye-agent-runtime.service`; real workflows still require packaged snapshots + readable MinIO/S3 blobs | S |
| `audit_service` | Hash-chain audit **verify** API + lifecycle (FastAPI) | No deploy unit. NOTE: chain **writes** are already live (BaseWorker → `audit_log`); only the verify/export API is undeployed | S |
| `backtest_engine` | Backtest execution (FastAPI) | No deploy unit; data/snapshot wiring | M |
| `broker_adapter_alpaca` | Alpaca broker adapter (FastAPI :7090) | No deploy unit; Alpaca creds. **Live-trading gated** — do not enable without explicit approval | M |
| `compliance_service` | Compliance checks (gRPC :7070 / HTTP :8008) | No deploy unit; gRPC infra | M |
| `data_ingestion` | Ingestion service (FastAPI + APScheduler cron) | Not deployed as a service. Prices/macro/news already run via standalone timers, so the full service is **optional** | S (optional) |
| `guard_service` | Pre-trade guard / risk gating (gRPC :7040 / HTTP :8005) | No deploy unit; gRPC infra | M |
| `llm_gateway` | LiteLLM proxy **config** + virtual-key provisioning (no FastAPI app) | N/A — the proxy itself is deployed (`theeyebeta-litellm`, fixed in this pass). This dir is config/scripts only | — |
| `master_orchestrator` | Orchestration + risk-metrics scheduler (FastAPI :7050) | No deploy unit; it gates the `risk_metrics` writer (issue #4) | M |
| `oms` | Order management system (FastAPI :7080) | No deploy unit. **Live-trading-adjacent** — do not enable without explicit approval | L |
| `risk_service` | Risk-metrics computation/writer (gRPC :7060 / HTTP :8007) | Deploy unit **staged** (`deploy/systemd/staged/`, disabled). Real blocker for `risk_metrics` (#4) is **upstream, not the unit**: 0 portfolios / 0 positions, and `risk_metrics.portfolio_id` is a NOT NULL FK — nothing to compute. Also needs `make build-cpp` (`zinc_native._zinc_risk`). See `docs/ops/risk-metrics-activation.md` | M |
| `rnd_agent` | Research / R&D agent | No deploy unit; LLM wiring | M |
| `snapshot_packager` | Daily snapshot packaging (FastAPI :7011) | No deploy unit; object storage (MinIO/S3) | M |

## Notes

- `services/api/` is an empty placeholder — the real external API lives in the sibling
  `TheEyeBetaDataAPI` repo (see `docs/api-gateway.md`).
- Open tracking issues from this pass: #3 (signals cutover), #4 (risk_metrics writer),
  #5 (supabase-sync broken + product decision).
- **#4 update (2026-06-15):** `theeyebeta.risk_metrics` is empty because the platform runs
  **no portfolios and holds no positions** — not because the writer was undeployed. The table
  has a `NOT NULL` FK to `theeyebeta.portfolios`, positions are written only by the
  live-trading-gated OMS, and nothing seeds portfolios. Empty is therefore the *correct* state
  today (cf. the empty `audit_log` finding). `risk_service` is now deploy-ready (staged unit +
  config), but stays inactive until a real book exists. Activation checklist:
  `docs/ops/risk-metrics-activation.md`.
