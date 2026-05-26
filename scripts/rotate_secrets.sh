#!/usr/bin/env bash
# Rotate SOPS-managed TheEyeBeta secrets.
#
# Usage:
#   scripts/rotate_secrets.sh --env dev
#   scripts/rotate_secrets.sh --env prod --commit --deploy --remote theeyebeta-mac --remote-dir ~/theeyebeta

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET_ENV="dev"
DO_COMMIT=0
DO_DEPLOY=0
KEEP_PLAINTEXT=0
REMOTE_HOST="${SECRET_ROTATION_REMOTE_HOST:-theeyebeta-mac}"
REMOTE_DIR="${SECRET_ROTATION_REMOTE_DIR:-~/theeyebeta}"

usage() {
  cat <<'EOF'
Usage: scripts/rotate_secrets.sh [options]

Options:
  --env <name>          Secret environment to rotate (default: dev)
  --commit              Commit encrypted secret changes
  --deploy              SSH to remote host, pull, decrypt .env, and run tb deploy
  --remote <host>       SSH host for deploy (default: $SECRET_ROTATION_REMOTE_HOST or theeyebeta-mac)
  --remote-dir <path>   Repo path on remote (default: $SECRET_ROTATION_REMOTE_DIR or ~/theeyebeta)
  --keep-plaintext      Leave secrets/<env>.enc.yaml.plain on disk for manual review
  -h, --help            Show this help

Manual provider keys are requested interactively:
  ANTHROPIC_API_KEY, OPENAI_API_KEY, ALPACA_API_KEY_PAPER, ALPACA_API_SECRET_PAPER.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --env)
      TARGET_ENV="${2:?--env requires a value}"
      shift 2
      ;;
    --commit)
      DO_COMMIT=1
      shift
      ;;
    --deploy)
      DO_DEPLOY=1
      shift
      ;;
    --remote)
      REMOTE_HOST="${2:?--remote requires a value}"
      shift 2
      ;;
    --remote-dir)
      REMOTE_DIR="${2:?--remote-dir requires a value}"
      shift 2
      ;;
    --keep-plaintext)
      KEEP_PLAINTEXT=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

ENC_FILE="${REPO_ROOT}/secrets/${TARGET_ENV}.enc.yaml"
PLAIN_FILE="${REPO_ROOT}/secrets/${TARGET_ENV}.enc.yaml.plain"
TMP_DIR="$(mktemp -d)"

cleanup() {
  rm -rf "${TMP_DIR}"
  if [[ "${KEEP_PLAINTEXT}" -ne 1 ]]; then
    rm -f "${PLAIN_FILE}"
  fi
}
trap cleanup EXIT

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing required command: $1" >&2
    exit 1
  fi
}

resolve_python() {
  if command -v python3 >/dev/null 2>&1; then
    echo python3
    return
  fi
  if command -v python >/dev/null 2>&1; then
    echo python
    return
  fi
  echo "Missing required command: python3 or python" >&2
  exit 1
}

prompt_secret() {
  local name="$1"
  local value=""
  while [[ -z "${value}" ]]; do
    read -r -s -p "Enter new ${name}: " value
    echo
    if [[ -z "${value}" ]]; then
      echo "${name} cannot be empty." >&2
    fi
  done
  printf '%s' "${value}"
}

set_env_value() {
  local key="$1"
  local value="$2"
  ROTATE_KEY="${key}" ROTATE_VALUE="${value}" ROTATE_FILE="${PLAIN_FILE}" "${PYTHON_BIN}" - <<'PY'
from pathlib import Path
import os

key = os.environ["ROTATE_KEY"]
value = os.environ["ROTATE_VALUE"]
path = Path(os.environ["ROTATE_FILE"])
lines = path.read_text(encoding="utf-8").splitlines()
replacement = f"{key}={value}"

for idx, line in enumerate(lines):
    if line.startswith(f"{key}="):
        lines[idx] = replacement
        break
else:
    if lines and lines[-1] != "":
        lines.append("")
    lines.append(replacement)

path.write_text("\n".join(lines) + "\n", encoding="utf-8")
PY
}

pem_to_dotenv() {
  awk 'NF { gsub(/\r/, ""); printf "%s\\n", $0 }' "$1" | sed 's/\\n$//'
}

require_cmd git
require_cmd openssl
require_cmd sops
PYTHON_BIN="$(resolve_python)"

if ! command -v htpasswd >/dev/null 2>&1; then
  echo "Missing required command: htpasswd (install apache2-utils/httpd-tools)." >&2
  exit 1
fi

if [[ ! -f "${ENC_FILE}" ]]; then
  echo "Encrypted secrets file not found: ${ENC_FILE}" >&2
  echo "Create it first from secrets/${TARGET_ENV}.enc.yaml.template or docs/secrets.md." >&2
  exit 1
fi

if [[ -e "${PLAIN_FILE}" ]]; then
  echo "Refusing to overwrite existing plaintext file: ${PLAIN_FILE}" >&2
  exit 1
fi

echo "Decrypting ${ENC_FILE} -> ${PLAIN_FILE}"
sops --decrypt --output-type dotenv "${ENC_FILE}" > "${PLAIN_FILE}"
chmod 600 "${PLAIN_FILE}"

echo
echo "Manual provider key rotation required before continuing:"
echo "  1. Anthropic: https://console.anthropic.com/"
echo "  2. OpenAI:    https://platform.openai.com/api-keys"
echo "  3. Alpaca:    https://app.alpaca.markets/paper/dashboard/overview"
echo

ANTHROPIC_API_KEY="$(prompt_secret ANTHROPIC_API_KEY)"
OPENAI_API_KEY="$(prompt_secret OPENAI_API_KEY)"
ALPACA_API_KEY_PAPER="$(prompt_secret ALPACA_API_KEY_PAPER)"
ALPACA_API_SECRET_PAPER="$(prompt_secret ALPACA_API_SECRET_PAPER)"

echo
echo "Generating new JWT RS256 keypair..."
JWT_PRIVATE_PEM="${TMP_DIR}/jwt_private.pem"
JWT_PUBLIC_PEM="${TMP_DIR}/jwt_public.pem"
openssl genrsa -out "${JWT_PRIVATE_PEM}" 4096 >/dev/null 2>&1
openssl rsa -in "${JWT_PRIVATE_PEM}" -pubout -out "${JWT_PUBLIC_PEM}" >/dev/null 2>&1

echo "Hashing new admin password with bcrypt..."
ADMIN_PASSWORD=""
ADMIN_PASSWORD_CONFIRM=""
while [[ -z "${ADMIN_PASSWORD}" || "${ADMIN_PASSWORD}" != "${ADMIN_PASSWORD_CONFIRM}" ]]; do
  read -r -s -p "Enter new ADMIN_PASSWORD: " ADMIN_PASSWORD
  echo
  read -r -s -p "Confirm new ADMIN_PASSWORD: " ADMIN_PASSWORD_CONFIRM
  echo
  if [[ -z "${ADMIN_PASSWORD}" ]]; then
    echo "ADMIN_PASSWORD cannot be empty." >&2
  elif [[ "${ADMIN_PASSWORD}" != "${ADMIN_PASSWORD_CONFIRM}" ]]; then
    echo "Admin password values did not match." >&2
  fi
done
ADMIN_PASSWORD_BCRYPT="$(htpasswd -bnB admin "${ADMIN_PASSWORD}" | sed 's/^admin://')"
unset ADMIN_PASSWORD ADMIN_PASSWORD_CONFIRM

set_env_value "ANTHROPIC_API_KEY" "${ANTHROPIC_API_KEY}"
set_env_value "OPENAI_API_KEY" "${OPENAI_API_KEY}"
set_env_value "ALPACA_API_KEY_PAPER" "${ALPACA_API_KEY_PAPER}"
set_env_value "ALPACA_API_SECRET_PAPER" "${ALPACA_API_SECRET_PAPER}"
set_env_value "JWT_PRIVATE_KEY" "$(pem_to_dotenv "${JWT_PRIVATE_PEM}")"
set_env_value "JWT_PUBLIC_KEY" "$(pem_to_dotenv "${JWT_PUBLIC_PEM}")"
set_env_value "ADMIN_PASSWORD_BCRYPT" "${ADMIN_PASSWORD_BCRYPT}"

unset ANTHROPIC_API_KEY OPENAI_API_KEY ALPACA_API_KEY_PAPER ALPACA_API_SECRET_PAPER ADMIN_PASSWORD_BCRYPT

echo "Re-encrypting ${ENC_FILE}"
sops --encrypt --input-type dotenv --output-type yaml "${PLAIN_FILE}" > "${ENC_FILE}"

if [[ "${KEEP_PLAINTEXT}" -eq 1 ]]; then
  echo "Plaintext kept for review: ${PLAIN_FILE}"
else
  rm -f "${PLAIN_FILE}"
fi

git add "${ENC_FILE}"
if [[ "${DO_COMMIT}" -eq 1 ]]; then
  git commit -m "chore(secrets): rotate ${TARGET_ENV} secrets"
else
  echo "Skipped commit. Review and commit with:"
  echo "  git commit -m \"chore(secrets): rotate ${TARGET_ENV} secrets\""
fi

if [[ "${DO_DEPLOY}" -eq 1 ]]; then
  echo "Deploying rotated secrets on ${REMOTE_HOST}:${REMOTE_DIR}"
  ssh "${REMOTE_HOST}" "set -euo pipefail; cd ${REMOTE_DIR}; git pull --ff-only; ENV=${TARGET_ENV} bash scripts/decrypt-env.sh ${TARGET_ENV}; tb deploy"
else
  echo "Skipped deploy. To deploy later:"
  echo "  ssh ${REMOTE_HOST} 'cd ${REMOTE_DIR} && git pull --ff-only && ENV=${TARGET_ENV} bash scripts/decrypt-env.sh ${TARGET_ENV} && tb deploy'"
fi

echo
echo "Manual final step: revoke the old Alpaca paper trading key in the Alpaca dashboard."
