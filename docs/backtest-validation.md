# Backtest validation (Phase 10)

Critical correctness gates for `backtest-engine` (P-BT-02). All tests live in
`services/backtest_engine/tests/test_validation.py` and are marked `@pytest.mark.validation`.

Run:

```bash
pytest services/backtest_engine/tests/test_validation.py -m validation -v
```

## 1. No look-ahead

**Risk:** Future snapshots or decisions leak into day *T* simulation, inflating backtest
returns.

**Guards** (`backtest_engine.validation`):

| Function | Purpose |
|----------|---------|
| `assert_snapshot_date(snapshot_date, pipeline_date)` | Rejects snapshots dated after the pipeline day |
| `assert_decision_book_no_lookahead(book, pipeline_date)` | Rejects decision weights keyed on future dates |
| `guard_decision_callback` / `guard_engine_strategy` | Wired into `BacktestRunner` production path |

**Test:** `test_no_lookahead_raises_when_t_plus_one_snapshot_injected` injects a T+1
snapshot into the date-T pipeline and expects `LookAheadViolation`.

**Test:** `test_no_lookahead_raises_when_future_decision_in_book` and
`test_no_lookahead_guard_blocks_engine_run_with_future_decisions` cover decision-book
leakage.

## 2. Survivorship bias

**Risk:** Using today's index membership for historical dates overstates returns.

**Mitigation** (`backtest_engine.universe`):

- `is_symbol_tradable(as_of, listed_at, delisted_at)` mirrors Postgres point-in-time SQL.
- `symbols_for_date` / `union_universe` only include instruments with
  `listed_at <= as_of` and `delisted_at > as_of` (or null).

**Test:** `test_survivorship_delisted_instrument_in_universe_pre_delist_only` seeds logic for
a name delisted mid-window and asserts membership before/after `delisted_at`.

**Test:** `test_survivorship_delisting_liquidates_at_last_available_price` buys pre-delisting,
stops Parquet bars at delist, targets weight 0 afterward, and asserts executions include a
sell at the last available close.

## 3. PnL reconciliation vs live

**Risk:** Engine slippage/commission model drifts from production fills.

**Harness** (`backtest_engine.reconcile`):

- Replays a fixed live week through `zinc_native.bt.Engine` with the same decisions and
  prices.
- Compares `live_week_net_pnl` vs `engine_net_pnl` via `assert_pnl_within_bps` (default **1
  bp**).

**Test:** `test_pnl_reconciliation_live_week_within_one_bp` replays buy/hold/sell
weights (forward-filled between live fills) and asserts independent live simulation
matches the engine path within 1 bp.

**Slippage:** `test_slippage_model_is_positive_and_realistic` asserts the default formula
in `validation.slippage_fraction` is positive and within 0.5–200 bps for liquid names.

## Acceptance (Phase 10)

| Gate | Status |
|------|--------|
| No look-ahead | `LookAheadViolation` + 3 unit tests |
| Survivorship | PIT universe + delist liquidation test |
| Live PnL replay | ≤ 1 bp tolerance test |
| Documentation | This file |

All three validation tests must pass before Phase 10 sign-off.
