# MASTER_ADMIN MFA Enrollment

`MASTER_ADMIN` accounts must have TOTP enabled before the admin service will issue a full session. If a `MASTER_ADMIN` password login succeeds but MFA is missing, `POST /admin/auth/login` returns `mfa_enrollment_required=true` and an `enrollment_token` instead of access tokens.

## Source of Truth

The admin service authenticates against these tables:

- `theeyebeta.admin_users`
- `theeyebeta.admin_user_roles`
- `theeyebeta.admin_roles`

The MFA columns are on `theeyebeta.admin_users`: `totp_secret`, `totp_enabled`, `totp_verified_at`, `totp_backup_codes`, `mfa_failed_attempts`, and `mfa_locked_until`.

The `iam.users` table is not used by `services/admin_service/auth.py` or `services/admin_service/auth_mfa.py` for admin MFA. On this deployment, the request-shaped query `SELECT id, email, mfa_enrolled FROM iam.users WHERE role = 'MASTER_ADMIN';` does not match the live schema because `iam.users` has `user_uuid`, not `id`, and no admin MFA columns.

## Check Enrollment

```bash
set -a && source .env && set +a
psql "${ADMIN_DATABASE_URL/+psycopg/}" -P pager=off <<'SQL'
SELECT u.id,
       u.username,
       u.email,
       r.name AS role,
       u.totp_enabled AS mfa_enrolled,
       u.totp_secret IS NOT NULL AS has_totp_secret,
       u.totp_verified_at,
       u.mfa_failed_attempts,
       u.mfa_locked_until
  FROM theeyebeta.admin_users u
  JOIN theeyebeta.admin_user_roles ur ON ur.user_id = u.id
  JOIN theeyebeta.admin_roles r ON r.id = ur.role_id
 WHERE r.name = 'MASTER_ADMIN';
SQL
```

## Preferred API Enrollment

Use this when the admin API is running and you have the `MASTER_ADMIN` password.

1. Password login:

```bash
LOGIN_JSON=$(
  curl -fsS -X POST http://127.0.0.1:7200/admin/auth/login \
    -H 'Content-Type: application/json' \
    -d '{"username":"master","password":"'"${MASTER_ADMIN_PASSWORD}"'"}'
)
ENROLLMENT_TOKEN=$(jq -r '.enrollment_token' <<<"$LOGIN_JSON")
```

2. Generate the TOTP secret through the service endpoint:

```bash
ENROLL_JSON=$(
  curl -fsS -X POST http://127.0.0.1:7200/admin/auth/mfa/enroll \
    -H 'Content-Type: application/json' \
    -d '{"enrollment_token":"'"${ENROLLMENT_TOKEN}"'"}'
)
MASTER_ADMIN_TOTP_SECRET=$(jq -r '.secret' <<<"$ENROLL_JSON")
```

3. Store the secret in `.env` or the sops-managed secret source:

```bash
printf 'MASTER_ADMIN_TOTP_SECRET=%s\n' "$MASTER_ADMIN_TOTP_SECRET" >> .env
```

4. Generate the current TOTP and confirm:

```bash
TOTP_CODE=$(uv run python - <<'PY'
import os
import pyotp
print(pyotp.TOTP(os.environ["MASTER_ADMIN_TOTP_SECRET"]).now())
PY
)

curl -fsS -o /dev/null -X POST http://127.0.0.1:7200/admin/auth/mfa/confirm \
  -H 'Content-Type: application/json' \
  -d '{"enrollment_token":"'"${ENROLLMENT_TOKEN}"'","totp_code":"'"${TOTP_CODE}"'"}'
```

Save the backup codes returned by `/mfa/enroll` in the team password manager. They are returned once.

## Recovery Enrollment Via DB

Use this when `MASTER_ADMIN` login is blocked and the API enrollment flow cannot be reached. This follows the same data model used by `services/admin_service/auth_mfa.py`.

1. Generate a secret with the same library used by the service:

```bash
MASTER_ADMIN_TOTP_SECRET=$(uv run python - <<'PY'
import pyotp
print(pyotp.random_base32())
PY
)
```

2. Enroll the account directly:

```bash
set -a && source .env && set +a
psql "${ADMIN_DATABASE_URL/+psycopg/}" \
  -v username='master' \
  -v secret="$MASTER_ADMIN_TOTP_SECRET" <<'SQL'
UPDATE theeyebeta.admin_users
   SET totp_secret = :'secret',
       totp_enabled = true,
       totp_verified_at = now(),
       mfa_failed_attempts = 0,
       mfa_locked_until = NULL
 WHERE username = :'username'
   AND is_active
RETURNING id, username, email, totp_enabled AS mfa_enrolled,
          totp_secret IS NOT NULL AS has_totp_secret, totp_verified_at;
SQL
```

3. Persist the secret outside git:

```bash
printf 'MASTER_ADMIN_TOTP_SECRET=%s\n' "$MASTER_ADMIN_TOTP_SECRET" >> .env
```

For a fresh deploy where the secret already exists in `.env`, reuse it in step 2 instead of generating a new value.

## Verify Login

After enrollment, a password login should return `mfa_required=true`. Complete MFA with the generated TOTP code:

```bash
LOGIN_JSON=$(
  curl -fsS -X POST http://127.0.0.1:7200/admin/auth/login \
    -H 'Content-Type: application/json' \
    -d '{"username":"master","password":"'"${MASTER_ADMIN_PASSWORD}"'"}'
)
MFA_TOKEN=$(jq -r '.mfa_token' <<<"$LOGIN_JSON")

TOTP_CODE=$(uv run python - <<'PY'
import os
import pyotp
print(pyotp.TOTP(os.environ["MASTER_ADMIN_TOTP_SECRET"]).now())
PY
)

curl -fsS -X POST http://127.0.0.1:7200/admin/auth/mfa/verify \
  -H 'Content-Type: application/json' \
  -d '{"mfa_token":"'"${MFA_TOKEN}"'","totp_code":"'"${TOTP_CODE}"'"}' \
  | jq '{role, token_type, has_access_token: (.access_token != null)}'
```

Expected result:

```json
{
  "role": "MASTER_ADMIN",
  "token_type": "bearer",
  "has_access_token": true
}
```

## 2026-06-16 Recovery Note

The live `master` account was recovered via the direct DB path because the full admin app could not start locally due to an unrelated import-time syntax error in `services/admin_service/api/guard.py`. The auth routes were then verified in an isolated FastAPI app using the real `auth.py` / `auth_mfa.py` routes, live Postgres, live Redis, and a generated TOTP from `MASTER_ADMIN_TOTP_SECRET`.
