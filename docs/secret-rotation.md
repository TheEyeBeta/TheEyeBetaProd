# Secret Rotation Runbook

This runbook rotates secrets stored in `secrets/<env>.enc.yaml` with SOPS + age.
Use [scripts/rotate_secrets.sh](../scripts/rotate_secrets.sh) as the primary
entrypoint.

## Scope

The rotation command updates:

- `ANTHROPIC_API_KEY` - manual provider key
- `OPENAI_API_KEY` - manual provider key
- `ALPACA_API_KEY_PAPER` - manual provider key
- `ALPACA_API_SECRET_PAPER` - manual provider key
- `JWT_PRIVATE_KEY` - generated with `openssl genrsa -out new.pem 4096`
- `JWT_PUBLIC_KEY` - generated with `openssl rsa -pubout`
- `ADMIN_PASSWORD_BCRYPT` - generated from an operator password prompt via `htpasswd -B`

Other secrets in the encrypted file are preserved.

## Prerequisites

Install local tooling:

```bash
brew install sops age openssl
brew install httpd
```

Linux equivalent:

```bash
sudo apt-get install -y sops age openssl apache2-utils
```

Confirm you can decrypt the target environment:

```bash
ENV=dev bash scripts/decrypt-env.sh dev
```

Confirm the working tree has no unrelated secret edits:

```bash
git status --short -- secrets scripts docs
```

## Manual Provider Key Steps

These steps must happen outside the script because provider APIs and dashboards
control key issuance.

1. Anthropic: create a new API key at `https://console.anthropic.com/`.
2. OpenAI: create a new API key at `https://platform.openai.com/api-keys`.
3. Alpaca paper trading: create a new paper key/secret in the Alpaca dashboard.
4. Keep old provider keys active until the deploy verification passes.
5. After verification, revoke the old Alpaca paper key in the Alpaca dashboard.

## Rotate Dev Secrets

Preview the workflow without committing or deploying:

```bash
bash scripts/rotate_secrets.sh --env dev
```

The script:

1. Decrypts `secrets/dev.enc.yaml` into `secrets/dev.enc.yaml.plain`.
2. Prompts for the new manual provider keys.
3. Generates a new JWT private/public keypair.
4. Prompts for the new admin password and bcrypt-hashes it with `htpasswd -B`.
5. Rewrites the rotated keys in the plaintext file.
6. Re-encrypts to `secrets/dev.enc.yaml`.
7. Deletes the plaintext file unless `--keep-plaintext` was passed.
8. Stages the encrypted file.

Review the encrypted-file diff metadata:

```bash
git diff --cached -- secrets/dev.enc.yaml
```

Commit and deploy in one flow:

```bash
bash scripts/rotate_secrets.sh \
  --env dev \
  --commit \
  --deploy \
  --remote theeyebeta-mac \
  --remote-dir ~/theeyebeta
```

The deploy step runs on the Mac mini:

```bash
git pull --ff-only
ENV=dev bash scripts/decrypt-env.sh dev
tb deploy
```

## Rotate Prod Secrets

Use the same command with `--env prod` once `secrets/prod.enc.yaml` exists:

```bash
bash scripts/rotate_secrets.sh \
  --env prod \
  --commit \
  --deploy \
  --remote theeyebeta-mac \
  --remote-dir ~/theeyebeta
```

## Verification

After deployment:

```bash
ssh theeyebeta-mac 'cd ~/theeyebeta && tb status'
```

Verify:

- `llm-gateway` is healthy.
- Admin login works with the new password.
- JWT-protected admin routes accept freshly issued tokens.
- A small OpenAI/Anthropic test request succeeds.
- Alpaca paper account calls succeed.
- No service is crash-looping after `tb deploy`.

## Rollback

If the system fails after rotation:

1. Do not revoke old provider keys yet.
2. Revert the secret rotation commit.
3. Redeploy:

```bash
ssh theeyebeta-mac 'cd ~/theeyebeta && git pull --ff-only && ENV=dev bash scripts/decrypt-env.sh dev && tb deploy'
```

4. Confirm `tb status`.
5. Investigate locally before retrying rotation.

## Plaintext Handling

`secrets/<env>.enc.yaml.plain` is a temporary plaintext file and must never be
committed. The script deletes it automatically unless `--keep-plaintext` is used.
When using `--keep-plaintext`, remove it after review:

```bash
rm -f secrets/dev.enc.yaml.plain
```

## Final Provider Cleanup

After deployment verification passes:

1. Revoke the old Alpaca paper key in the Alpaca dashboard.
2. Revoke old Anthropic/OpenAI keys if they are no longer used by any other
   environment.
3. Record the rotation in the operations log or incident/change ticket.
