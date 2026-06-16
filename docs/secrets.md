# Secrets Management

theeyebeta encrypts all secrets with **SOPS + age**.  
The age private key lives in **1Password** — never on disk unprotected, never in git.

---

## How It Works

```
.env  (gitignored)          secrets/dev.enc.yaml  (git-tracked, encrypted)
  ↑                                   ↑
  │  decrypt-env.sh                   │  sops --encrypt
  └──────────────────────────────────-┘
```

- `secrets/dev.enc.yaml` — encrypted YAML committed to git. Each value is independently
  encrypted so `git diff` shows which keys changed (not their values).
- `.env` — plaintext, gitignored, generated on each machine by running the decrypt script.
- `secrets/dev.enc.yaml.template` — committed plaintext template showing all key names
  with placeholder values. Safe to commit; contains no secrets.

---

## First-Time Setup (per machine)

### 1. Install tools

```bash
# age
curl -LO https://github.com/FiloSottile/age/releases/latest/download/age-v1.2.0-linux-amd64.tar.gz
tar -xz age-v1.2.0-linux-amd64.tar.gz && sudo mv age/age age/age-keygen /usr/local/bin/

# sops
SOPS_VER=$(curl -s https://api.github.com/repos/mozilla/sops/releases/latest | grep tag_name | cut -d'"' -f4)
curl -LO "https://github.com/mozilla/sops/releases/download/${SOPS_VER}/sops-${SOPS_VER}.linux.amd64"
sudo install -m 755 sops-*.linux.amd64 /usr/local/bin/sops
```

### 2. Generate your age keypair

```bash
mkdir -p ~/.config/sops/age
age-keygen -o ~/.config/sops/age/keys.txt
# Output: Public key: age1xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

### 3. Save the private key in 1Password

1. Open 1Password → **New Item → Secure Note**.
2. Title: `theeyebeta age key`.
3. Paste the **entire contents** of `~/.config/sops/age/keys.txt` into the **password field**.
4. Save.

> The private key file (`~/.config/sops/age/keys.txt`) stays on disk for local use.
> If the machine is lost, recover from 1Password: paste the content back to that path.

### 4. Register your public key

Edit `secrets/.sops.yaml` — replace the `age1PLACEHOLDER...` line with your public key:

```yaml
creation_rules:
  - path_regex: \.enc\.yaml$
    age: >-
      age1xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

If other team members need access, add their public keys comma-separated:

```yaml
    age: >-
      age1alice...,
      age1bob...
```

### 5. Encrypt the dev secrets (first time)

```bash
cp secrets/dev.enc.yaml.template secrets/dev.enc.yaml.plain
# Edit dev.enc.yaml.plain — fill in real dev values
nano secrets/dev.enc.yaml.plain

sops --encrypt \
     --input-type dotenv \
     --output-type yaml \
     secrets/dev.enc.yaml.plain > secrets/dev.enc.yaml

rm secrets/dev.enc.yaml.plain   # never leave plaintext on disk
git add secrets/dev.enc.yaml
git commit -m "chore(secrets): add encrypted dev secrets"
```

---

## Day-to-Day: Get Your .env

```bash
bash scripts/decrypt-env.sh          # → .env (dev)
ENV=staging bash scripts/decrypt-env.sh  # → .env (staging)
```

Or use 1Password CLI to inject directly (no .env file on disk):

```bash
op run -- make up
```

---

## Editing Existing Secrets

```bash
sops secrets/dev.enc.yaml    # opens in $EDITOR, re-encrypts on save
```

---

## Adding a New Secret Key

1. Add the key with a placeholder to `secrets/dev.enc.yaml.template` (commit this).
2. Open the encrypted file: `sops secrets/dev.enc.yaml`
3. Add the new key-value pair and save.

---

## Rotating or Revoking a Key

```bash
# Edit secrets/.sops.yaml — add new public key, remove old one
# Then re-encrypt all files:
sops updatekeys secrets/dev.enc.yaml
git add secrets/dev.enc.yaml
git commit -m "chore(secrets): rotate age key"
```

---

## CI / GitHub Actions

Store the age private key as a GitHub Actions secret named `SOPS_AGE_KEY`:

1. In 1Password, copy the contents of `theeyebeta age key` (the full `keys.txt` text).
2. In GitHub repo → **Settings → Secrets → Actions** → New secret → `SOPS_AGE_KEY`.

In the CI workflow, the decrypt script automatically uses `$SOPS_AGE_KEY` when the local
`~/.config/sops/age/keys.txt` file does not exist:

```yaml
# .github/workflows/ci.yml (already configured)
- name: Decrypt dev secrets
  env:
    SOPS_AGE_KEY: ${{ secrets.SOPS_AGE_KEY }}
  run: bash scripts/decrypt-env.sh
```

---

## Security Properties

| Property | Detail |
|----------|--------|
| Key type | age (X25519 + ChaCha20-Poly1305) |
| Granularity | Each YAML value encrypted independently — diffs show changed keys |
| Plaintext | Never touches git; `.plain` files and `.env` are gitignored |
| Private key | Stored in 1Password; never hardcoded, never in CI logs |
| Audit trail | `sops` metadata block in every `.enc.yaml` records MAC, creation time, key fingerprints |

---

## Secrets Inventory

| Key | Used by | Notes |
|-----|---------|-------|
| `POSTGRES_PASSWORD` | All services | DB superuser password |
| `REDIS_PASSWORD` | Reserved (not wired) | Future Redis AUTH password — dev/compose runs without AUTH today |
| `MINIO_ROOT_USER` | Storage service | MinIO access key |
| `MINIO_ROOT_PASSWORD` | Storage service | MinIO secret key |
| `ANTHROPIC_API_KEY` | AI services | Claude API |
| `OPENAI_API_KEY` | AI services | OpenAI API |
| `ALPACA_API_KEY_PAPER` | Order service | Paper trading only |
| `ALPACA_API_SECRET_PAPER` | Order service | Paper trading only |
| `JWT_PRIVATE_KEY` | Auth service | RS256 signing key (PEM) |
| `JWT_PUBLIC_KEY` | Auth service | RS256 verification key (PEM) |
| `ADMIN_USERNAME` | Admin service | Admin UI login |
| `ADMIN_PASSWORD_BCRYPT` | Admin service | bcrypt hash, not plaintext |
