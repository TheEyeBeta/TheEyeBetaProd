# Database Roles

## Application roles

| Role | Purpose | Key grants |
|------|---------|------------|
| `theeyebeta` / `tb_app` | Admin-service, workers | CRUD on operational tables; no INSERT on `audit_checkpoints` after migration 0029 |
| `theeyebeta_audit_writer` | audit-service NATS consumer | INSERT-only on `audit_checkpoints` via RLS |
| `tb_rnd_readonly` | Research read access | SELECT on non-sensitive tables |

## WORM audit checkpoints (migration 0029)

`audit_checkpoints` has row-level security:

- INSERT allowed for `theeyebeta` role via policy (migrated to `theeyebeta_audit_writer` only)
- UPDATE and DELETE denied for all application roles
- Only `theeyebeta_audit_writer` may append checkpoint rows

Deploy audit-service connecting as a credential granted `theeyebeta_audit_writer`.

## Bootstrap

```bash
make db-migrate   # applies through 0029_audit_worm_policy
```
