# Remediation pass — 2026-06-15

One-shot remediation of TheEyeBeta2025Live (run on `claude-opus-4-8`). Each numbered item is
a separate commit. Host-only systemd/DB state changes are recorded here because they leave no
other repo artifact. Constraint honored throughout: `public.*` not touched (deprecating);
`iam.*` read-only.

## P3 — cleanup

### [6] API supervision drift — `theeyebeta-api.service` masked

- The live external API runs as the **user** unit `theeyebeta-dataapi.service` (gunicorn, `:7000`).
- The system unit `theeyebeta-api.service` was disabled/dead and redundant.
- The host-only unit file was archived to `deploy/systemd/archived/theeyebeta-api.service`,
  removed from `/etc/systemd/system`, then `systemctl mask`ed (the path had to be freed first —
  it was a real file, not a `/usr/lib` shadow).
- Result: `is-enabled=masked`, `is-active=inactive`; `:7000` still served by `dataapi`.
- Reversible: `sudo systemctl unmask theeyebeta-api.service` + restore the archived file.

### [10] Unused daemons masked — engine / trask / watcher

- `theeyebeta-engine.service` (Trade Engine), `theeyebeta-trask.service` (monitoring daemon),
  and `theeyebeta-watcher.service` (repo auto-update/restart) were all inactive + disabled,
  with **no running equivalent** (no listeners). Their `ExecStart` points at a different tree
  (`/home/the-eye-beta/TheEyeBeta2025/TheEyeBetaLocal`), i.e. they belong to the Local/dev
  checkout, not this Prod host.
- Decision (opus): unused here, no deployment plan on this host → mask (also prevents an
  accidental start of the **trade engine**, which is desirable). Not started.
- Each host-only unit was archived to `deploy/systemd/archived/`, removed from
  `/etc/systemd/system`, then masked. All three now `is-enabled=masked`.
- Reversible: `sudo systemctl unmask <unit>` + restore the archived file. If they are meant
  to run, they should be deployed from the `TheEyeBetaLocal` tree, not unmasked here.
