# Repository Layout

This document is the canonical reference for the **theeyebeta** (`TheEyeBetaProd`) monorepo
directory tree. All agents and contributors must follow this structure. Update here first, then
create files. For the fuller annotated version (with deployment status per service, port map,
etc.) see [architecture.md §14](architecture.md#14-repository-layout).

## Top-Level Tree

```
TheEyeBetaProd/
├── .claude/                  # Claude Code agent rules + skills
│   ├── rules/
│   │   ├── 01-code-style.md
│   │   ├── 02-testing.md
│   │   ├── 03-security.md
│   │   ├── 04-infrastructure.md
│   │   ├── cpp.md, frontend.md, python.md, sql.md, tests.md
│   ├── agents/
│   │   ├── dev.md             # General dev subagent (lint, test, build)
│   │   └── infra.md           # Infra subagent (compose, migrations)
│   └── skills/
│       └── doc-sync/          # Keeps docs/ in sync with code changes — see SKILL.md
├── .cursor/                  # Cursor IDE rules
├── .github/
│   └── workflows/
│       ├── ci.yml             # lint -> [py-test, cpp-build, sbom, docs] -> integration-tests -> smoke-staging -> all-ok
│       ├── deploy.yml         # push to main -> SSH -> Mac mini
│       ├── release.yml        # tag v*.*.* -> build images + tb CLI + GitHub Release
│       ├── paper-smoke.yml    # nightly, self-hosted runner, hits live paper-trading endpoints
│       └── bench.yml
├── .sops.yaml                # SOPS encryption config (age key IDs)
├── .pre-commit-config.yaml
├── .clang-format
├── .gitignore
├── CLAUDE.md                 # Master agent guide
├── Makefile                  # self-documenting — `make help` lists every target
├── README.md
├── SERVICES_STATUS.md        # live deployed-vs-scaffolded snapshot for services/
├── cliff.toml                 # git-cliff CHANGELOG generation (Conventional Commits)
├── docker-compose.yml        # dev infra + the 4 containerized app services
├── pyproject.toml            # uv workspace root
│
├── config/
│   ├── agents/hierarchy.yaml # AI staff reports-to tree (~30 agents)
│   └── litellm.yaml          # LiteLLM model routing (OpenAI gpt-5 / gpt-4o-mini)
│
├── cpp/                      # C++20 source (CMake + Conan 2), nanobind bindings -> zinc_native
│   ├── include/, src/, tests/, bench/, bindings/
│   └── conanfile.py
│
├── db/
│   ├── alembic.ini
│   ├── migrations/
│   │   ├── versions/         # 0000-0035 — one schema, `theeyebeta` (see data-model.md)
│   │   └── env.py
│   ├── reference/             # universe_v1.txt (500), universe_v2.txt (~4,651), universe_eod.txt (~11,365)
│   ├── seeds/                 # agents.py, agent_hierarchy.py, seed_instruments.py, seed_paper_risk_portfolio.py,
│   │                          # exchanges.sql, strategies.sql, universe.yaml
│   ├── verify.py, verify_full.py
│   └── seed_paper_risk_portfolio.py
│
├── deploy/                    # the REAL bare-metal deployment artifacts
│   ├── systemd/                # ~40 service/timer unit files (workers, agent_runtime, staged risk_service, ...)
│   │   ├── archived/            # 4 decommissioned units
│   │   └── staged/              # built, intentionally disabled
│   ├── install_systemd_units.sh
│   ├── README.md
│   └── MACMINI_OPERATOR_RUNBOOK.md
│
├── docs/
│   ├── adr/                  # Architecture Decision Records (0001-0011, single canonical dir)
│   ├── ops/                  # disaster-recovery, alerting, secrets, mfa-enrollment, paper-trading-runbook, ...
│   ├── infra/                 # database-roles.md, tailscale-acl-policy.json
│   ├── api/                   # generated OpenAPI/ReDoc output (`make docs-api`)
│   ├── templates/
│   │   ├── Dockerfile.template
│   │   ├── README.md         # README template for services
│   │   └── adr.md            # ADR template
│   ├── architecture.md
│   ├── repo-layout.md        # THIS FILE
│   ├── data-model.md
│   ├── db-state-map.md       # generated diagnostic — do not hand-edit
│   ├── db-engineer-SKILL.md  # mandatory before any DB-adjacent change
│   ├── agents.md
│   ├── admin-service.md
│   ├── ci.md
│   └── secrets.md
│
├── infra/                     # dev-infra config mounted into docker-compose containers
│   ├── compose/, caddy/, cloudflared/, grafana/, otelcol/, postgres/init/, prometheus/, tempo/
│   ├── systemd/               # stale — 1 leftover file, ignore; real units are deploy/systemd/
│   └── k8s/                   # placeholder only (.gitkeep), not in use
│
├── libs/                       # Shared Python/C++ libraries
│   ├── zinc_native/, zinc_proto/, zinc_schemas/, zinc_test/
│
├── scripts/
│   ├── macro_ingestor/         # standalone FRED macro pipeline (registry + backfill + refresh)
│   ├── diagnose_db_state.py    # generates docs/db-state-map.md
│   ├── backup_db.sh, test_restore.sh, prelive_check.py, check_no_public_refs.py, decrypt-env.sh
│
├── services/                   # 16 dirs — see architecture.md §3.1 for deployed vs. code-complete
│   ├── admin_service/           # deployed (docker-compose, :7200)
│   ├── agent_runtime/           # deployed (systemd, :8004)
│   ├── api/                     # EMPTY placeholder — real external API is the sibling TheEyeBetaDataAPI repo
│   ├── audit_service/
│   ├── backtest_engine/
│   ├── broker_adapter_alpaca/   # deployed (systemd, theeye-broker-adapter-alpaca.service, :7090, paper mode)
│   ├── compliance_service/     # deployed (systemd, theeye-compliance-service.service, :7070/:8008)
│   ├── data_ingestion/          # deployed (docker-compose, :7010)
│   ├── guard_service/
│   ├── llm_gateway/              # config/scripts only — the running proxy is the LiteLLM container
│   ├── master_orchestrator/    # deployed (systemd, theeye-master-orchestrator.service, :7050)
│   ├── oms/                     # deployed (systemd, theeye-oms.service, :7080, paper mode)
│   ├── risk_service/             # unit staged but disabled
│   ├── rnd_agent/
│   ├── snapshot_packager/        # deployed (systemd, theeye-snapshot-packager.service, :7011)
│   └── worker/                   # EMPTY placeholder
│
├── tb/                          # tb CLI (published as tb-theeyebeta-cli)
│
├── tests/
│   ├── unit/, integration/, smoke/
│
└── workers/                     # the actual production data pipeline — timer-driven via deploy/systemd
    ├── base_worker.py            # all workers inherit this; writes audit_log on completion
    ├── macro_ingestion_worker.py, macro_pipeline.py, macro_regime_worker.py, macro_features.py
    ├── massive_ingestion_worker.py, intraday_ingestion_worker.py
    ├── sector_aggregation_worker.py, market_cap_fetch_worker.py, market_cap_threshold_worker.py
    ├── indicator_compute_worker.py, theeyebeta_indicator_worker.py
    ├── gap_sentinel_worker.py, latest_snapshot_worker.py, daily_pipeline_runner.py
    ├── reporting_chain_worker.py, supabase_sync_worker.py   # supabase-sync is masked/broken
    └── fred_client.py, calendar.py, universe_tiers.py
```

## Naming Conventions

- Services: `snake_case` directories under `services/` (e.g. `agent_runtime`), referred to by
  `kebab-case` names in docker-compose/systemd (e.g. `agent-runtime`/`theeye-agent-runtime`).
- Python packages/modules: `snake_case`.
- C++ files: `snake_case.cpp` / `snake_case.h`.
- Migration files: `NNNN_short_description.py` (Alembic auto-numbering, currently 0000-0035).
- systemd units: `theeye-<name>.service` / `.timer` (note: no `beta` in most worker unit names,
  except `theeyebeta-admin.service` and `theeyebeta-litellm.service`, which do include it —
  `systemctl ... | grep eye` alone will miss the latter two).
