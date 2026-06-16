# Secrets Operations

This repo must not rely on one global plaintext `.env` for production systemd
services. The live host uses per-unit plaintext files for runtime and an age
encrypted root bundle for recovery.

## Secret Inventory

Audited files:

- `.env.age` is the encrypted replacement for the former root `.env`.
- `.env.example` and `.env.laptop.example` are templates only.
- `.env.<service>` files are host-local runtime files and are ignored by git.

Sensitive variables found in the former root `.env` bundle:

```text
ADMIN_DATABASE_URL
ALPACA_API_KEY_PAPER
ALPACA_API_KEY_PAPER_NASDAQ
ALPACA_API_KEY_PAPER_NYSE
ALPACA_API_KEY_PAPER_ZINC
ALPACA_API_SECRET_PAPER
ALPACA_API_SECRET_PAPER_NASDAQ
ALPACA_API_SECRET_PAPER_NYSE
ALPACA_API_SECRET_PAPER_ZINC
ALPHAVANTAGE_KEY
CURSOR_API_KEY
DATABASE_URL
FINNHUB_API_KEY
FMP_API_KEY
FRED_API_KEY
INGEST_DATABASE_URL
LITELLM_KEY_AGENT_RUNTIME_EXECUTORS
MASSIVE_API_KEY
MASTER_ADMIN_TOTP_SECRET
NEWSAPI_KEY
OPENAI_API_KEY
REDIS_OPS_URL
REDIS_URL
SMTP_PASSWORD
SUPABASE_ANON_KEY
SUPABASE_SERVICE_ROLE_KEY
TB_APP_PASSWORD
TB_RND_PASSWORD
```

Sensitive template variables in `.env.example`:

```text
ADMIN_PASSWORD_BCRYPT
ALPACA_API_KEY_PAPER
ALPACA_API_SECRET_PAPER
ANTHROPIC_API_KEY
APCA_API_KEY_ID
APCA_API_SECRET_KEY
FRED_API_KEY
GRAFANA_ADMIN_PASSWORD
INGEST_DATABASE_URL
LITELLM_DB_PASSWORD
LITELLM_MASTER_KEY
MINIO_ROOT_PASSWORD
OPENAI_API_KEY
POSTGRES_PASSWORD
SMTP_PASSWORD
```

Sensitive template variables in `.env.laptop.example`:

```text
DATABASE_URL
INGEST_DATABASE_URL
TAILSCALE_DATABASE_URL
TB_APP_PASSWORD
TB_RND_PASSWORD
```

## Runtime Scope

Production systemd units must use one scoped `EnvironmentFile` per unit:

```text
/home/the-eye-beta/TheEyeBeta2025/TheEyeBetaProd/.env.<unit-name>
```

Examples:

```text
theeye-oms.service                         -> .env.theeye-oms
theeye-broker-adapter-alpaca.service       -> .env.theeye-broker-adapter-alpaca
theeye-agent-runtime.service               -> .env.theeye-agent-runtime
theeyebeta-admin.service                   -> .env.theeyebeta-admin
theeyebeta-litellm.service                 -> .env.theeyebeta-litellm
```

These files are plaintext because systemd consumes them directly. They must be
mode `0600`, owned by `the-eye-beta`, and never committed. Regenerate them from
the encrypted bundle after rotation.

## Bootstrap Admin Removal

Admin-service no longer authenticates an env bootstrap user. `ADMIN_USERNAME`
and `ADMIN_PASSWORD_BCRYPT` must not grant `MASTER_ADMIN`. Admin login is backed
only by `theeyebeta.admin_users` plus `theeyebeta.admin_user_roles`, and
`MASTER_ADMIN` still requires TOTP enrollment.

The old lowercase live env keys `master` and `analyst` were removed from the
encrypted root bundle and are not copied into scoped service env files.

## Encrypt Root Env

Install age:

```bash
sudo apt-get install -y age
```

Generate an operator key if one does not already exist:

```bash
mkdir -p ~/.config/sops/age
age-keygen -o ~/.config/sops/age/keys.txt
chmod 600 ~/.config/sops/age/keys.txt
age-keygen -y ~/.config/sops/age/keys.txt
```

Encrypt:

```bash
age -r <age-public-key> -o .env.age .env
```

Decrypt for recovery or rotation:

```bash
age -d -i ~/.config/sops/age/keys.txt -o .env .env.age
chmod 600 .env
```

After generating service-specific env files, remove the root plaintext `.env`
again. Runtime units should not depend on it.

## Rotation Procedure

1. Decrypt `.env.age` to a temporary `.env`.
2. Rotate the target credential at the upstream provider.
3. Update only the affected variable names.
4. Regenerate the affected `.env.<service>` files.
5. Re-encrypt `.env.age`.
6. Remove the plaintext `.env`.
7. Run `sudo systemctl daemon-reload`.
8. Restart only services whose scoped env changed.

Before committing, run:

```bash
git status --short
git diff --check
git log --all -p | grep -i "secret\|password\|api_key" | head -20
```
