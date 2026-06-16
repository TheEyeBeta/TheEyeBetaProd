# Audit Log — Hash Chain Spec and Operations Runbook

## Chain spec

Every row in `theeyebeta.audit_log` is linked to its predecessor by a SHA-256
hash chain.  This makes tampering with any historical row detectable.

### Schema columns relevant to the chain

| Column | Type | Purpose |
|--------|------|---------|
| `id` | bigint (PK) | Monotone sequence, defines row order |
| `ts` | timestamptz | Wall-clock timestamp of the event |
| `actor` | text | Service or user that wrote the row |
| `action` | text | Dotted verb, e.g. `approve.order` |
| `entity_type` | text | Table name of the affected entity |
| `entity_id` | text | PK of the affected entity as string |
| `payload` | jsonb | Full mutation context |
| `prev_hash` | bytea | `row_hash` of the immediately preceding row |
| `row_hash` | bytea | SHA-256 of `prev_hash \|\| canonical_json(row)` |

### Hash computation

```
canonical_json(row) = JSON({
    "action":      row.action,
    "actor":       row.actor,
    "entity_id":   row.entity_id,
    "entity_type": row.entity_type,
    "payload":     row.payload,
    "ts":          row.ts.astimezone(UTC).isoformat(),
}, sort_keys=True, separators=(",", ":"))

row_hash = SHA-256(prev_hash || canonical_json(row).encode("utf-8"))
```

The first row in the table chains from the **genesis hash**:

```python
GENESIS_SEED  = b"theeyebeta-genesis-2026-05-21"
GENESIS_HASH  = SHA-256(GENESIS_SEED)   # fixed constant
```

### Locking guarantee

`audit_service.chain.append_chained_row` holds PostgreSQL advisory lock
`pg_advisory_xact_lock(7110)` for the duration of each insert transaction.
This serialises all writers so that two concurrent inserts cannot read the
same `prev_hash` and produce a fork in the chain.

---

## Writers

All audit writes **must** go through `audit_service.chain.append_chained_row`.
Direct `INSERT` to `theeyebeta.audit_log` bypasses the advisory lock and will
corrupt the chain.

| Service | Module |
|---------|--------|
| OMS | `services/oms/src/oms/audit.py` → `append_chained_row` |
| Admin service | `services/admin_service/audit_log.py` → `append_chained_row` |
| Audit service consumer | `services/audit_service/src/audit_service/consumer.py` |

---

## Verifying the chain

### Prelive check (automatic)

The prelive check script (`scripts/prelive_check.py`, check #13) calls
`audit_service.chain.verify_chain(dsn)` on every `python -m admin.prelive`
run.  It reads all rows in id order, recomputes every hash from the genesis
seed, and fails with the first bad row id if any mismatch is found.

### Manual verification

```bash
# Full chain (all rows from genesis)
uv run python - <<'EOF'
import asyncio
from audit_service.chain import verify_chain
from workers.base_worker import worker_database_url

result = asyncio.run(verify_chain(worker_database_url()))
print(result)
EOF

# Time-range only (faster for large tables)
uv run python - <<'EOF'
import asyncio
from datetime import UTC, datetime, timedelta
from audit_service.chain import verify_range
from workers.base_worker import worker_database_url

to_ts   = datetime.now(tz=UTC)
from_ts = to_ts - timedelta(hours=24)
result  = asyncio.run(verify_range(worker_database_url(), from_ts=from_ts, to_ts=to_ts))
print(result)
EOF
```

### API endpoint

```
GET /admin/audit/chain/verify    # requires COMPLIANCE role
GET /admin/audit/verify?from=<iso>&to=<iso>
```

---

## What a broken chain means

A `MISMATCH` result means one of:

1. A row was **edited** in place after insertion.
2. A row was **deleted** (deletion is prohibited by policy — see CLAUDE.md §7).
3. A write used a direct `INSERT` bypassing the advisory lock (race) — two
   rows read the same `prev_hash` and both committed.  The second one has a
   valid individual hash but the chain is forked.

### Response to a broken chain

1. **Do not attempt to repair the chain in-place** — any fix is itself a
   mutation and will obscure the incident.
2. Capture the full table dump immediately:
   ```bash
   pg_dump -t theeyebeta.audit_log "$DATABASE_URL" > audit_log_incident_$(date +%s).sql
   ```
3. File an incident in Linear under the SECURITY project with the output of
   `verify_chain` including `first_bad_row_id` and `detail`.
4. Restore from the most recent WORM checkpoint (see `GET /admin/audit/checkpoints`)
   if row-level evidence is required for compliance.

---

## Deploy runbook reference

See [deploy.md](deploy.md) for the full deployment procedure.
The prelive check (step 5 of the deploy job) will block promotion if the
audit chain is broken post-deploy.
