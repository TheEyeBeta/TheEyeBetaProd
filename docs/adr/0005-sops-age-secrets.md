# ADR 0005: sops + age for Secrets Management

**Status:** Accepted — 2026-05-21
**Deciders:** Platform team
**Related:** [docs/secrets.md](../secrets.md), [docs/architecture.md §10](../architecture.md#10-secrets-management)

---

## Context

theeyebeta stores secrets that must be:

- **Git-versioned** alongside the code that uses them (reproducibility, auditability).
- **Encrypted at rest** — no plaintext ever in the repository.
- **Team-distributable** — a new team member can be onboarded by adding their public key.
- **CI-compatible** — decryption in GitHub Actions without human intervention.
- **Rotatable** — removing a team member's access does not require re-creating every secret.

The secrets include database passwords, LLM API keys (Anthropic, OpenAI), Alpaca trading keys, JWT signing keys, and bcrypt-hashed admin credentials.

---

## Decision

We will use **SOPS** (Secrets OPerationS) with **age** encryption.

- `.sops.yaml` at repo root and `secrets/` defines creation rules mapping `*.enc.yaml` files to recipient age public keys.
- Plaintext secrets are stored in `KEY=VALUE` dotenv format, encrypted to `secrets/<env>.enc.yaml`.
- Decrypt at runtime: `sops --decrypt --output-type dotenv secrets/dev.enc.yaml > .env`.
- Private keys stored in **1Password** as "theeyebeta age key"; CI reads from `SOPS_AGE_KEY` GitHub Actions secret.

---

## Consequences

### Positive
- Encrypted files are git-trackable YAML — `git diff` shows which keys changed without revealing values.
- age is a modern, simple encryption format (X25519 + ChaCha20-Poly1305). No GPG web-of-trust complexity.
- Adding/removing a recipient is a single `sops updatekeys` command; no secret values need to change.
- 1Password stores the private key securely; recovery from any device takes one CLI command.
- Zero external service dependency for decryption in dev (unlike Vault, Doppler, AWS SM).

### Negative
- Developers must install sops and age before first use. One extra onboarding step.
- SOPS v3 and the age backend have occasional rough edges (key format changes, `sops updatekeys` behaviour). Pin sops version in CI and pre-commit.
- Initial private key distribution requires a secure side-channel (1Password invitation or in-person).
- SOPS does not support streaming decryption of large secrets files; all values are decrypted at once.

### Neutral
- The `secrets/dev.enc.yaml.template` committed to the repo shows all key names with placeholder values — safe to view but requires a private key to decrypt actual values.
- Production and staging have separate `*.enc.yaml` files with separate recipient sets.

---

## Alternatives Considered

| Option | Why rejected |
|--------|-------------|
| **HashiCorp Vault** | Requires a running Vault server; operational overhead on a single-host setup; overkill |
| **AWS Secrets Manager** | Cloud vendor lock-in; cost; requires outbound calls to decrypt; not self-hosted |
| **git-crypt** | GPG-based (complex key management); binary diff in git (unusable `git diff`); less active development |
| **Doppler** | SaaS; secrets leave the host for every decryption; vendor dependency |
| **Plaintext .env in .gitignore** | Not versioned; onboarding requires manual secret distribution with no audit trail |
| **sops + GPG** | GPG key management is notoriously brittle; age is strictly simpler and more secure |

---

## References

- [SOPS documentation](https://github.com/mozilla/sops)
- [age encryption specification](https://age-encryption.org/)
- [docs/secrets.md — full workflow](../secrets.md)
- [secrets/.sops.yaml](../../secrets/.sops.yaml)
- [scripts/decrypt-env.sh](../../scripts/decrypt-env.sh)
