#!/usr/bin/env bash
# decrypt-env.sh — Decrypt a sops-encrypted secrets file to .env
#
# Usage:
#   bash scripts/decrypt-env.sh           # decrypts secrets/dev.enc.yaml → .env
#   ENV=prod bash scripts/decrypt-env.sh  # decrypts secrets/prod.enc.yaml → .env
#   bash scripts/decrypt-env.sh staging   # positional arg also accepted
#
# Requirements:
#   - sops  (https://github.com/mozilla/sops)
#   - age private key at ~/.config/sops/age/keys.txt
#     OR SOPS_AGE_KEY env var set (used in CI)
#
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Resolve target environment: arg > ENV var > default "dev"
TARGET_ENV="${1:-${ENV:-dev}}"
ENC_FILE="${REPO_ROOT}/secrets/${TARGET_ENV}.enc.yaml"
OUT_FILE="${REPO_ROOT}/.env"

# ── Validate ──────────────────────────────────────────────────────────────────
if [[ ! -f "${ENC_FILE}" ]]; then
  echo "✖ Encrypted file not found: ${ENC_FILE}" >&2
  echo "  Have you run the first-time encrypt step?" >&2
  echo "  See: docs/secrets.md" >&2
  exit 1
fi

if ! command -v sops &>/dev/null; then
  echo "✖ sops not installed." >&2
  echo "  Linux:  wget -O /usr/local/bin/sops https://github.com/mozilla/sops/releases/latest/download/sops-v*.linux.amd64 && chmod +x /usr/local/bin/sops" >&2
  echo "  macOS:  brew install sops" >&2
  exit 1
fi

# ── Check for age key (local file or CI env var) ──────────────────────────────
AGE_KEY_FILE="${SOPS_AGE_KEY_FILE:-${HOME}/.config/sops/age/keys.txt}"
if [[ -z "${SOPS_AGE_KEY:-}" ]] && [[ ! -f "${AGE_KEY_FILE}" ]]; then
  echo "✖ age private key not found." >&2
  echo "  Expected: ${AGE_KEY_FILE}" >&2
  echo "  Or set:   export SOPS_AGE_KEY=\"<key contents>\"  (for CI)" >&2
  echo "  The private key is in 1Password: 'theeyebeta age key'" >&2
  exit 1
fi

# ── Decrypt ───────────────────────────────────────────────────────────────────
echo "▶ Decrypting ${TARGET_ENV} secrets → .env"

sops --decrypt \
     --output-type dotenv \
     "${ENC_FILE}" > "${OUT_FILE}"

# Verify the output is non-empty and not accidentally a YAML block
if [[ ! -s "${OUT_FILE}" ]]; then
  echo "✖ Decryption produced an empty .env" >&2
  rm -f "${OUT_FILE}"
  exit 1
fi

# Count exported variables
VAR_COUNT=$(grep -c '^[A-Z]' "${OUT_FILE}" || true)
echo "✔ Wrote ${VAR_COUNT} variables to .env (${TARGET_ENV})"
echo "  Source with: source .env   OR   use with: op run -- make up"
