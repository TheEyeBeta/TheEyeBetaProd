# zinc C++ microbenchmarks

Google Benchmark executables (one per module):

| Target | Workload |
|--------|----------|
| `risk_bench` | `historical_var` on 10k returns; `correlation_matrix` on 252×100 |
| `ta_bench` | `atr` / `adx` on 1k bars; `hmm_regime` on 500 points |
| `opt_bench` | `mvo` on 50 assets; `hrp` on 100 assets |
| `bt_bench` | 252-day engine run, 500-symbol universe |
| `oms_bench` | `StateMachine::transition` throughput |

## Local run

```bash
make build-cpp PRESET=linux-release
cd build/linux-release/cpp/bench
./risk_bench --benchmark_format=json --benchmark_out=risk.json
```

## CI regression gate

Workflow [`.github/workflows/bench.yml`](../../.github/workflows/bench.yml) runs on PRs and nightly,
writes JSON, and fails when any benchmark median is **>10% slower** than
`baselines/linux-release.json` on `main` (Git LFS).

To verify the gate locally after changing a baseline:

```bash
python scripts/compare_benchmarks.py \
  cpp/bench/baselines/linux-release.json \
  build/linux-release/cpp/bench/results/ \
  --threshold 1.10
```

To simulate a failing PR, introduce a deliberate slowdown (e.g. extra sleep in a hot path) and
confirm `compare_benchmarks.py` exits non-zero when the ratio exceeds `1.50` for a 50% regression.
