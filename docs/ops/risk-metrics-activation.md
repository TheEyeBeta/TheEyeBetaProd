# Activating the `risk_metrics` writer (issue #4)

**Status (2026-06-15): staged, intentionally inactive.**

`theeyebeta.risk_metrics` is empty. This is the **correct** state today — not a deployment
gap. This doc records *why*, and the exact checklist to turn the writer on once there is a
real portfolio to measure.

## Why it is empty (root cause)

`risk_service` computes per-portfolio risk (VaR-95, CVaR-95, max drawdown, gross/net
exposure, beta-to-SPY, concentration HHI via the `zinc_native` C++ kernels) and appends one
row to `theeyebeta.risk_metrics`. It is **reactive** — it writes only when called, via the
HTTP bridge (`/v1/compute-portfolio-metrics`, `/v1/validate-order`) or gRPC.

The live DB currently holds:

| Table | Rows |
|---|---|
| `theeyebeta.instruments` | 35,784 |
| `theeyebeta.portfolios` | **0** |
| `theeyebeta.positions` | **0** |
| `theeyebeta.risk_metrics` | **0** |

The schema enforces the dependency:

```sql
risk_metrics.portfolio_id  uuid NOT NULL  REFERENCES theeyebeta.portfolios(id)
```

With zero portfolios a `risk_metrics` row **cannot be inserted**, and
`load_portfolio_context()` raises `ValueError: portfolio <id> not found` for any id. Positions
are written **only** by the OMS (`services/oms/src/oms/db.py`), which is live-trading-gated;
nothing seeds `portfolios`. So the table is empty because the platform holds no book — exactly
like the empty `audit_log`. **Do not fabricate a portfolio just to make rows appear.**

## What is already staged

- `deploy/systemd/staged/theeye-risk-service.service` — the writer's unit, disabled and kept
  out of the top-level `deploy/systemd/` so `install_systemd_units.sh` will not install it yet.
- Config knobs documented in `.env.example` (`RISK_SERVICE_URL`,
  `RISK_METRICS_PORTFOLIO_IDS`, `RISK_METRICS_INTERVAL_SECONDS`, host/port vars).
- The driver already exists in code: `master_orchestrator`'s `RiskMetricsScheduler`
  (`services/master_orchestrator/src/master_orchestrator/scheduler.py`), which POSTs the HTTP
  bridge every `RISK_METRICS_INTERVAL_SECONDS` for each id in `RISK_METRICS_PORTFOLIO_IDS`.

## Activation checklist (run only when a real portfolio exists)

1. **Build the C++ risk kernels** — `make build-cpp`. This compiles `zinc_native._zinc_risk`
   (and siblings) and copies the `.so` into `libs/zinc_native/zinc_native/`. Without it
   `import risk_service.app` fails with `ModuleNotFoundError: zinc_native._zinc_risk`.
   Requires `conan` + `cmake` on the host.
2. **Confirm a portfolio + positions exist** —
   `SELECT count(*) FROM theeyebeta.portfolios;` must be `> 0`, and that portfolio should have
   rows in `theeyebeta.positions`. Capture the portfolio UUID(s).
3. **Wire config** in `.env`: set `RISK_SERVICE_URL=http://127.0.0.1:8007` and
   `RISK_METRICS_PORTFOLIO_IDS=<uuid[,uuid...]>` (and optionally
   `RISK_METRICS_INTERVAL_SECONDS`). The scheduler skips itself unless both are set.
4. **Install + start the writer**: move
   `deploy/systemd/staged/theeye-risk-service.service` → `deploy/systemd/`, then
   `sudo deploy/install_systemd_units.sh` and `sudo systemctl enable --now theeye-risk-service`.
   Verify `curl -s localhost:8007/health` returns `{"status":"ok"}`.
5. **Run the driver** — deploy `master_orchestrator` (it hosts the scheduler in its lifespan),
   or trigger one recompute manually to smoke-test:
   `curl -XPOST localhost:8007/v1/compute-portfolio-metrics -H 'content-type: application/json' -d '{"portfolio_id":"<uuid>"}'`.
6. **Confirm rows** —
   `SELECT count(*), max(ts) FROM theeyebeta.risk_metrics;` should advance after each interval.

## Rollback

`sudo systemctl disable --now theeye-risk-service`, move the unit back to
`deploy/systemd/staged/`, and unset `RISK_SERVICE_URL` / `RISK_METRICS_PORTFOLIO_IDS`. No data
migration is involved — `risk_metrics` is append-only telemetry.
