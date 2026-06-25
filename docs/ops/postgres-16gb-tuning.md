# PostgreSQL tuning — 16 GB host

**Applies to:** Prod Mac mini / Ubuntu host with ~16 GB RAM running PostgreSQL 16
(`postgresql@16-main`) alongside theeyebeta workers, systemd services, and a desktop session.

**Related:** [remediation-2026-06-15.md](remediation-2026-06-15.md),
[GRAND_AUDIT §12.4](../reports/GRAND_AUDIT_2026-06-12.md)

---

## Why this matters

On a 16 GB machine the typical RAM budget is:

| Consumer | Typical RSS |
|----------|-------------|
| PostgreSQL | 2–3 GiB |
| Legacy `theeyebeta-engine` (must be **off**) | ~1.7 GiB if running |
| Desktop (Chromium + Cursor) | 2–3 GiB |
| theeye-* trading services | ~1 GiB combined |
| Nightly Python workers (peak) | 1–2 GiB spike |

Heavy swap use (>50%) makes workers, `prelive_check`, and journalctl sluggish — an
operational risk during paper trading.

Operator tooling now surfaces this:

- `uv run tb meta doctor` — `memory` and `legacy_daemons` checks
- `uv run python scripts/prelive_check.py` — checks **HOST MEMORY** and **LEGACY DAEMONS**

---

## Recommended settings (16 GB host)

Edit the cluster config (Debian/Ubuntu example):

```bash
sudo nano /etc/postgresql/16/main/postgresql.conf
```

| Parameter | Aggressive (avoid) | **16 GB target** | Notes |
|-----------|-------------------|------------------|-------|
| `shared_buffers` | 3974MB (~4 GB) | **2048MB** | ~12% of RAM; leave headroom for Python |
| `effective_cache_size` | 11923MB | **8192MB** | Planner hint only, not allocated |
| `work_mem` | 15898kB (~16 MB) | **8192kB** | Per sort/hash node; admin SQL uses `SET LOCAL work_mem = '16MB'` |
| `maintenance_work_mem` | default | **512MB** | OK for VACUUM/CREATE INDEX off-peak |
| `max_connections` | 100+ | **80** | Each idle connection still costs RAM |

After changes:

```bash
sudo systemctl reload postgresql@16-main
# or restart if reload does not pick up shared_buffers:
sudo systemctl restart postgresql@16-main
```

Verify:

```sql
SHOW shared_buffers;
SHOW work_mem;
SHOW effective_cache_size;
```

---

## Legacy daemon hygiene

These units belong to `TheEyeBetaLocal`, not Prod. They must stay **masked** on the Prod host:

- `theeyebeta-engine.service` (~1.7 GiB when active)
- `theeyebeta-trask.service`
- `theeyebeta-watcher.service`

```bash
systemctl is-active theeyebeta-engine   # must NOT be "active"
sudo systemctl stop theeyebeta-engine
sudo systemctl mask theeyebeta-engine
```

See [remediation-2026-06-15.md § P3 [10]](remediation-2026-06-15.md).

---

## Operational habits

1. **Close Chromium** during the 21:35 UTC nightly pipeline window.
2. **Monitor swap:** `free -h` — aim for swap used < 500 MiB under normal load.
3. **Run doctor before pipeline:** `uv run tb meta doctor`
4. **Do not run** Docker Compose Postgres *and* host Postgres for the same DB — pick one.

---

## Rollback

Keep a copy of the previous `postgresql.conf` before editing. Restore and reload if query
latency regresses after lowering `shared_buffers` (unlikely on this workload; most benefit
comes from freeing host RAM for workers).
