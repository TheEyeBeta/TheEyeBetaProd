"""Comprehensive architectural-invariant verification for theeyebeta.

Cross-checks every invariant of the theeyebeta database against the live
PostgreSQL instance at $DATABASE_URL.

Usage:
    uv run python db/verify_full.py

Exit code 0 if all checks pass, 1 otherwise.
"""

from __future__ import annotations

import os
import re
import sys
import urllib.parse as _up
import uuid
from typing import Any

import psycopg
import psycopg.errors
from dotenv import load_dotenv

load_dotenv()

# ── Environment ───────────────────────────────────────────────────────────────

_raw_url = os.environ.get("DATABASE_URL", "")
# Strip SQLAlchemy driver prefix (+asyncpg, +psycopg, etc.) if present.
DATABASE_URL: str = re.sub(r"\+\w+", "", _raw_url, count=1)
TB_APP_PASSWORD: str = os.environ.get("TB_APP_PASSWORD", "")
TB_RND_PASSWORD: str = os.environ.get("TB_RND_PASSWORD", "")

# ── ANSI colour helpers (disabled when NO_COLOR is set) ───────────────────────

_colour = not os.environ.get("NO_COLOR")


def _green(s: str) -> str:
    """Wrap *s* in ANSI green if colours are enabled."""
    return f"\033[32m{s}\033[0m" if _colour else s


def _red(s: str) -> str:
    """Wrap *s* in ANSI red if colours are enabled."""
    return f"\033[31m{s}\033[0m" if _colour else s


def _bold(s: str) -> str:
    """Wrap *s* in ANSI bold if colours are enabled."""
    return f"\033[1m{s}\033[0m" if _colour else s


TICK = _green("✓")
CROSS = _red("✗")

# ── Result tracking ───────────────────────────────────────────────────────────

# (section_number, check_name, passed, detail)
_results: list[tuple[int, str, bool, str]] = []
# section_number → (passed, total)
_section_counts: dict[int, tuple[int, int]] = {}
_current_section: int = 0


def _record(name: str, passed: bool, detail: str = "") -> None:
    """Record a single check result and print it immediately."""
    _results.append((_current_section, name, passed, detail))
    p, t = _section_counts.get(_current_section, (0, 0))
    _section_counts[_current_section] = (p + (1 if passed else 0), t + 1)
    mark = TICK if passed else CROSS
    if detail:  # noqa: SIM108 — multiline form is more readable than a long ternary here
        suffix = f"  → {detail}"
    else:
        suffix = ""
    print(f"  {mark} {name}{suffix}", flush=True)


def _section(n: int, name: str) -> None:
    """Print a section header and update the current section counter."""
    global _current_section
    _current_section = n
    print(f"\n─── SECTION {n}: {name} ───", flush=True)


def _section_summary(n: int) -> None:
    """Print a per-section pass/total tally."""
    p, t = _section_counts.get(n, (0, 0))
    colour_fn = _green if p == t else _red
    print(f"  [{colour_fn(f'{p}/{t}')} checks passed in this section]", flush=True)


# ── Connection helpers ────────────────────────────────────────────────────────


def _swap_creds(url: str, user: str, password: str) -> str:
    """Return *url* with the username/password replaced by *user*/*password*.

    Host, port and database path are preserved.
    """
    p = _up.urlparse(url)
    host = p.hostname or "localhost"
    port = p.port or 5432
    netloc = f"{user}:{_up.quote(password, safe='')}@{host}:{port}"
    return p._replace(netloc=netloc).geturl()


def _conn(url: str = DATABASE_URL, **kwargs: Any) -> psycopg.Connection[Any]:  # noqa: ANN401 — psycopg kwargs are heterogeneous by design
    """Open a psycopg3 connection with autocommit enabled."""
    return psycopg.connect(url, autocommit=True, **kwargs)


def _app_url() -> str:
    """Connection string for the tb_app role."""
    return _swap_creds(DATABASE_URL, "tb_app", TB_APP_PASSWORD)


def _rnd_url() -> str:
    """Connection string for the tb_rnd_readonly role."""
    return _swap_creds(DATABASE_URL, "tb_rnd_readonly", TB_RND_PASSWORD)


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 1 — Database & Extensions
# ─────────────────────────────────────────────────────────────────────────────


def section_1(conn: psycopg.Connection[Any]) -> None:
    """Verify database-level settings and installed extensions."""
    _section(1, "Database & Extensions")

    # Connection itself is already proven by reaching here, but record it.
    _record("Connect to DATABASE_URL succeeds", True)

    # Schema 'theeyebeta' exists
    row = conn.execute("SELECT 1 FROM pg_namespace WHERE nspname='theeyebeta'").fetchone()
    _record("Schema 'theeyebeta' exists", row is not None)

    # Schemas 'iam' and 'public' still exist
    for schema in ("iam", "public"):
        row = conn.execute("SELECT 1 FROM pg_namespace WHERE nspname=%s", (schema,)).fetchone()
        _record(f"Schema '{schema}' exists", row is not None)

    # Database-level search_path is 'theeyebeta, public'
    rows = conn.execute("""
        SELECT s.setconfig
        FROM pg_db_role_setting s
        JOIN pg_database d ON d.oid = s.setdatabase
        WHERE d.datname = 'TheEyeBeta2025Live'
        """).fetchall()
    cfg_vals: list[str] = [v for row in rows for v in (row[0] or [])]
    sp_entry = next((v for v in cfg_vals if "search_path" in v), None)
    sp_ok = sp_entry is not None and "theeyebeta, public" in sp_entry
    _record(
        "Database search_path is 'theeyebeta, public'",
        sp_ok,
        f"got: {sp_entry or 'not set'}",
    )

    # Extensions with non-null versions
    for ext in ("timescaledb", "vector", "pgcrypto", "pg_trgm"):
        row = conn.execute(
            "SELECT extversion FROM pg_extension WHERE extname=%s", (ext,)
        ).fetchone()
        ok = row is not None and row[0] is not None
        _record(
            f"Extension '{ext}' installed",
            ok,
            f"version: {row[0] if row else 'NOT FOUND'}",
        )

    # timescaledb in shared_preload_libraries
    row = conn.execute("SHOW shared_preload_libraries").fetchone()
    spl: str = row[0] if row else ""
    _record(
        "timescaledb in shared_preload_libraries",
        "timescaledb" in spl,
        f"got: {spl[:80]}",
    )

    # Alembic version
    expected_rev = "0010_data_snapshots"
    try:
        row = conn.execute("SELECT version_num FROM theeyebeta.alembic_version").fetchone()
        actual_rev: str | None = row[0] if row else None
        _record(
            f"Alembic version_num = '{expected_rev}'",
            actual_rev == expected_rev,
            f"got: {actual_rev}",
        )
    except Exception as exc:
        _record(f"Alembic version_num = '{expected_rev}'", False, str(exc))

    _section_summary(1)


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 2 — Roles
# ─────────────────────────────────────────────────────────────────────────────


def section_2(conn: psycopg.Connection[Any]) -> None:
    """Verify role existence, login capability and privilege grants."""
    _section(2, "Roles")

    db_name = "TheEyeBeta2025Live"
    for role in ("tb_app", "tb_rnd_readonly"):
        row = conn.execute("SELECT rolcanlogin FROM pg_roles WHERE rolname=%s", (role,)).fetchone()
        exists = row is not None
        can_login = bool(row[0]) if row else False
        _record(
            f"Role '{role}' exists with LOGIN",
            exists and can_login,
            "" if (exists and can_login) else f"exists={exists} rolcanlogin={can_login}",
        )

        row = conn.execute(
            "SELECT has_database_privilege(%s, %s, 'CONNECT')", (role, db_name)
        ).fetchone()
        _record(
            f"Role '{role}' has CONNECT on database {db_name}",
            row is not None and bool(row[0]),
        )

        row = conn.execute(
            "SELECT has_schema_privilege(%s, 'theeyebeta', 'USAGE')", (role,)
        ).fetchone()
        _record(
            f"Role '{role}' has USAGE on schema theeyebeta",
            row is not None and bool(row[0]),
        )

    # Default privileges: tb_rnd_readonly must NOT have INSERT/UPDATE/DELETE
    row = conn.execute("""
        SELECT defaclacl
        FROM pg_default_acl da
        JOIN pg_namespace n ON n.oid = da.defaclnamespace
        WHERE n.nspname = 'theeyebeta'
          AND da.defaclobjtype = 'r'
        """).fetchone()
    acl_entries: list[str] = list(row[0]) if (row and row[0]) else []
    rnd_entry = next((a for a in acl_entries if "tb_rnd_readonly" in a), "")
    # ACL format: "role=privileges/grantor"; a=INSERT, w=UPDATE, d=DELETE
    has_write = bool(re.search(r"tb_rnd_readonly=[^/]*[awd]", rnd_entry))
    _record(
        "Default privs for tb_rnd_readonly do NOT include INSERT/UPDATE/DELETE",
        not has_write,
        f"acl entry: {rnd_entry or 'none found'}",
    )

    _section_summary(2)


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 3 — Tables exist (32 base tables)
# ─────────────────────────────────────────────────────────────────────────────

EXPECTED_TABLES: dict[str, int] = {
    "exchanges": 6,
    "instruments": 15,
    "market_calendars": 6,
    "holidays": 3,
    "prices_daily": 11,
    "prices_intraday": 9,
    "corporate_actions": 9,
    "fundamentals": 16,
    "macro_indicators": 5,
    "news_articles": 9,
    "news_embeddings": 4,
    "agents": 9,
    "agent_runs": 12,
    "agent_decisions": 12,
    "agent_messages": 7,
    "agent_memory": 7,
    "guard_violations": 9,
    "proposals": 18,
    "accounts": 8,
    "portfolios": 5,
    "strategies": 5,
    "signals": 7,
    "orders": 20,
    "executions": 8,
    "positions": 10,
    "backtest_runs": 11,
    "backtest_results": 3,
    "risk_metrics": 11,
    "compliance_checks": 7,
    "model_runs": 12,
    "api_costs": 6,
    "audit_log": 9,
    "data_snapshots": 9,
}


def section_3(conn: psycopg.Connection[Any]) -> None:
    """Verify all 32 expected base tables exist with correct column counts."""
    _section(3, "Tables exist (32 base tables expected in theeyebeta)")

    rows = conn.execute("""
        SELECT table_name, count(*)::int AS col_count
        FROM information_schema.columns
        WHERE table_schema = 'theeyebeta'
        GROUP BY table_name
        """).fetchall()
    actual: dict[str, int] = {r[0]: r[1] for r in rows}

    for table, expected_cols in EXPECTED_TABLES.items():
        got = actual.get(table)
        if got is None:
            _record(f"Table '{table}' exists [{expected_cols} cols]", False, "table not found")
        elif got != expected_cols:
            _record(
                f"Table '{table}' has correct column count",
                False,
                f"expected {expected_cols} cols, got {got}",
            )
        else:
            _record(f"Table '{table}' exists with {expected_cols} columns", True)

    _section_summary(3)


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 4 — Critical column types
# ─────────────────────────────────────────────────────────────────────────────


def section_4(conn: psycopg.Connection[Any]) -> None:
    """Verify specific column types and CHECK constraints."""
    _section(4, "Critical column types")

    def col_info(table: str, col: str) -> tuple[str, str]:
        """Return (data_type, udt_name) from information_schema, or NOT FOUND."""
        r = conn.execute(
            """
            SELECT data_type, udt_name
            FROM information_schema.columns
            WHERE table_schema='theeyebeta' AND table_name=%s AND column_name=%s
            """,
            (table, col),
        ).fetchone()
        return (r[0], r[1]) if r else ("NOT FOUND", "NOT FOUND")

    def check_vector(table: str, col: str, dim: int) -> None:
        """Verify a column is vector(dim)."""
        dt, udt = col_info(table, col)
        if dt != "USER-DEFINED" or udt != "vector":
            _record(
                f"{table}.{col} is USER-DEFINED type 'vector'",
                False,
                f"data_type={dt}, udt_name={udt}",
            )
            return
        r = conn.execute(
            """
            SELECT atttypmod
            FROM pg_attribute a
            JOIN pg_class c ON c.oid = a.attrelid
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = 'theeyebeta'
              AND c.relname = %s
              AND a.attname = %s
            """,
            (table, col),
        ).fetchone()
        actual_dim = r[0] if r else -1
        _record(
            f"{table}.{col} is vector({dim})",
            actual_dim == dim,
            f"atttypmod (dimension): {actual_dim}",
        )

    check_vector("news_embeddings", "embedding", 1536)
    check_vector("agent_memory", "embedding", 1536)

    # bytea columns
    for table, col in [("audit_log", "row_hash"), ("audit_log", "prev_hash")]:
        dt, _ = col_info(table, col)
        _record(f"{table}.{col} is bytea", dt == "bytea", f"got: {dt}")

    def get_checks(table: str) -> dict[str, str]:
        """Return {constraint_name: definition} for CHECK constraints on table."""
        rows = conn.execute(
            """
            SELECT c.conname, pg_get_constraintdef(c.oid)
            FROM pg_constraint c
            JOIN pg_class r ON r.oid = c.conrelid
            JOIN pg_namespace n ON n.oid = r.relnamespace
            WHERE n.nspname = 'theeyebeta'
              AND r.relname = %s
              AND c.contype = 'c'
            """,
            (table,),
        ).fetchall()
        return {r[0]: r[1] for r in rows}

    # orders.status — 9 values
    orders_check_text = " ".join(get_checks("orders").values())
    status_9 = [
        "pending_approval",
        "approved",
        "submitted",
        "accepted",
        "partially_filled",
        "filled",
        "cancelled",
        "rejected",
        "expired",
    ]
    missing = [v for v in status_9 if v not in orders_check_text]
    _record(
        "orders.status CHECK contains all 9 status values",
        not missing,
        f"missing: {missing}" if missing else "",
    )

    # agent_decisions.decision
    dec_text = " ".join(get_checks("agent_decisions").values())
    dec_values = ["BUY", "SELL", "HOLD", "REDUCE", "EXIT", "OBSERVE"]
    missing = [v for v in dec_values if v not in dec_text]
    _record(
        "agent_decisions.decision CHECK: BUY,SELL,HOLD,REDUCE,EXIT,OBSERVE",
        not missing,
        f"missing: {missing}" if missing else "",
    )

    # agent_decisions.confidence BETWEEN 0 AND 1
    conf_ok = any(
        "confidence" in v and "0" in v and "1" in v for v in get_checks("agent_decisions").values()
    )
    _record("agent_decisions.confidence CHECK BETWEEN 0 AND 1", conf_ok)

    # guard_violations.violation_type — 7 types
    gv_text = " ".join(get_checks("guard_violations").values())
    violation_types = [
        "schema",
        "confidence_range",
        "missing_evidence",
        "tool_whitelist",
        "creative_content",
        "mandate_boundary",
        "forbidden_target",
    ]
    missing = [v for v in violation_types if v not in gv_text]
    _record(
        "guard_violations.violation_type CHECK contains all 7 types",
        not missing,
        f"missing: {missing}" if missing else "",
    )

    # proposals.status — 5 statuses
    prop_text = " ".join(get_checks("proposals").values())
    prop_statuses = ["pending", "approved", "rejected", "superseded", "applied"]
    missing = [v for v in prop_statuses if v not in prop_text]
    _record(
        "proposals.status CHECK contains 5 statuses",
        not missing,
        f"missing: {missing}" if missing else "",
    )

    # proposals.category — 6 categories
    prop_cats = [
        "strategy_param",
        "agent_constitution",
        "risk_rule",
        "compliance_rule_nonregulatory",
        "new_strategy",
        "architecture",
    ]
    missing = [v for v in prop_cats if v not in prop_text]
    _record(
        "proposals.category CHECK contains 6 categories",
        not missing,
        f"missing: {missing}" if missing else "",
    )

    _section_summary(4)


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 5 — Foreign Keys
# ─────────────────────────────────────────────────────────────────────────────

# (child_table, child_col, parent_table, parent_col)
EXPECTED_FKS: list[tuple[str, str, str, str]] = [
    ("instruments", "exchange_id", "exchanges", "id"),
    ("prices_daily", "instrument_id", "instruments", "id"),
    ("agent_runs", "agent_id", "agents", "id"),
    ("agent_decisions", "run_id", "agent_runs", "id"),
    ("guard_violations", "run_id", "agent_runs", "id"),
    ("guard_violations", "agent_id", "agents", "id"),
    ("orders", "portfolio_id", "portfolios", "id"),
    ("orders", "instrument_id", "instruments", "id"),
    ("orders", "decision_id", "agent_decisions", "id"),
    ("executions", "order_id", "orders", "id"),
    ("portfolios", "account_id", "accounts", "id"),
    ("positions", "portfolio_id", "portfolios", "id"),
    ("backtest_results", "backtest_id", "backtest_runs", "id"),
    ("compliance_checks", "order_id", "orders", "id"),
    ("proposals", "validation_backtest_id", "backtest_runs", "id"),
]


def section_5(conn: psycopg.Connection[Any]) -> None:
    """Verify critical FK relationships via information_schema."""
    _section(5, "Foreign Keys (sample critical ones)")

    rows = conn.execute("""
        SELECT
            kcu.table_name  AS child_table,
            kcu.column_name AS child_col,
            ccu.table_name  AS parent_table,
            ccu.column_name AS parent_col
        FROM information_schema.referential_constraints rc
        JOIN information_schema.key_column_usage kcu
            ON  kcu.constraint_name   = rc.constraint_name
            AND kcu.constraint_schema = rc.constraint_schema
        JOIN information_schema.key_column_usage ccu
            ON  ccu.constraint_name   = rc.unique_constraint_name
            AND ccu.constraint_schema = rc.unique_constraint_schema
            AND ccu.ordinal_position  = kcu.ordinal_position
        WHERE kcu.table_schema = 'theeyebeta'
        """).fetchall()
    fk_set: set[tuple[str, str, str, str]] = {(r[0], r[1], r[2], r[3]) for r in rows}

    for child, child_col, parent, parent_col in EXPECTED_FKS:
        ok = (child, child_col, parent, parent_col) in fk_set
        _record(f"FK: {child}.{child_col} → {parent}.{parent_col}", ok)

    _section_summary(5)


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 6 — Hypertables
# ─────────────────────────────────────────────────────────────────────────────

EXPECTED_HYPERTABLES: set[str] = {
    "prices_daily",
    "prices_intraday",
    "macro_indicators",
    "signals",
    "risk_metrics",
}


def section_6(conn: psycopg.Connection[Any]) -> None:
    """Verify TimescaleDB hypertables and compression policy."""
    _section(6, "Hypertables (5 expected)")

    rows = conn.execute("""
        SELECT hypertable_name, num_dimensions, num_chunks
        FROM timescaledb_information.hypertables
        WHERE hypertable_schema = 'theeyebeta'
        ORDER BY hypertable_name
        """).fetchall()
    actual_ht: set[str] = {r[0] for r in rows}
    ht_info: dict[str, tuple[int, int]] = {r[0]: (r[1], r[2]) for r in rows}

    for ht in sorted(EXPECTED_HYPERTABLES):
        ok = ht in actual_ht
        if ok:
            nd, nc = ht_info[ht]
            detail = f"dims={nd}, chunks={nc}"
        else:
            detail = "NOT FOUND"
        _record(f"Hypertable '{ht}' exists", ok, detail)

    extra = actual_ht - EXPECTED_HYPERTABLES
    _record(
        "Hypertable set is exactly the 5 expected",
        not extra,
        f"extra: {sorted(extra)}" if extra else "",
    )

    # prices_daily compression policy
    row = conn.execute("""
        SELECT schedule_interval
        FROM timescaledb_information.jobs
        WHERE proc_name = 'policy_compression'
          AND hypertable_name = 'prices_daily'
        """).fetchone()
    ok = row is not None and row[0] is not None
    _record(
        "prices_daily has compression policy (schedule_interval not null)",
        ok,
        f"schedule_interval: {row[0] if row else 'NOT FOUND'}",
    )

    _section_summary(6)


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 7 — Indexes
# ─────────────────────────────────────────────────────────────────────────────

EXPECTED_INDEXES: list[str] = [
    "idx_instruments_active",
    "idx_instruments_sector",
    "idx_prices_daily_uniq",
    "idx_prices_intraday_uniq",
    "idx_corp_actions_inst_date",
    "idx_fundamentals_inst",
    "idx_news_published",
    "idx_news_tickers",
    "idx_news_embed_hnsw",
    "idx_agent_runs_agent_started",
    "idx_decisions_inst",
    "idx_agent_msgs_run",
    "idx_agent_mem_hnsw",
    "idx_guard_violations_agent_ts",
    "idx_guard_violations_unresolved",
    "idx_proposals_status_created",
    "idx_proposals_target",
    "idx_proposals_category",
    "idx_orders_portfolio_status",
    "idx_orders_inst_created",
    "idx_compliance_order",
    "idx_model_runs_created",
    "idx_audit_entity",
    "idx_audit_actor_ts",
]
_UNIQUE_IDXS: set[str] = {"idx_prices_daily_uniq", "idx_prices_intraday_uniq"}
_GIN_IDXS: set[str] = {"idx_news_tickers"}
_HNSW_IDXS: set[str] = {"idx_news_embed_hnsw", "idx_agent_mem_hnsw"}


def section_7(conn: psycopg.Connection[Any]) -> None:
    """Verify existence and characteristics of critical indexes."""
    _section(7, "Indexes (sample critical ones)")

    rows = conn.execute(
        "SELECT indexname, indexdef FROM pg_indexes WHERE schemaname='theeyebeta'"
    ).fetchall()
    idx_map: dict[str, str] = {r[0]: r[1] for r in rows}

    for idx_name in EXPECTED_INDEXES:
        if idx_name not in idx_map:
            _record(f"Index '{idx_name}' exists", False, "NOT FOUND")
            continue
        defn = idx_map[idx_name]
        if idx_name in _UNIQUE_IDXS and "UNIQUE" not in defn.upper():
            _record(f"Index '{idx_name}' exists (UNIQUE)", False, f"not UNIQUE: {defn[:60]}")
        elif idx_name in _GIN_IDXS and "USING GIN" not in defn.upper():
            _record(f"Index '{idx_name}' exists (GIN)", False, f"not GIN: {defn[:60]}")
        else:
            _record(f"Index '{idx_name}' exists", True)

    # Exactly 2 HNSW indexes
    hnsw_rows = conn.execute("""
        SELECT indexname
        FROM pg_indexes
        WHERE schemaname = 'theeyebeta'
          AND indexdef LIKE '%USING hnsw%'
        ORDER BY indexname
        """).fetchall()
    hnsw_actual: set[str] = {r[0] for r in hnsw_rows}
    _record(
        "Exactly 2 HNSW indexes: idx_news_embed_hnsw, idx_agent_mem_hnsw",
        hnsw_actual == _HNSW_IDXS,
        f"found: {sorted(hnsw_actual)}" if hnsw_actual != _HNSW_IDXS else "",
    )

    _section_summary(7)


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 8 — Partitioning
# ─────────────────────────────────────────────────────────────────────────────


def section_8(conn: psycopg.Connection[Any]) -> None:
    """Verify audit_log partitioning structure and helper function."""
    _section(8, "Partitioning")

    # audit_log is a partitioned parent (relkind='p')
    row = conn.execute("""
        SELECT c.relkind
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'theeyebeta' AND c.relname = 'audit_log'
        """).fetchone()
    is_partitioned = row is not None and row[0] == "p"
    _record(
        "audit_log is a partitioned parent (relkind='p')",
        is_partitioned,
        f"relkind: {row[0] if row else 'NOT FOUND'}",
    )

    # At least 6 partitions
    row = conn.execute("""
        SELECT count(*)
        FROM pg_inherits
        WHERE inhparent = 'theeyebeta.audit_log'::regclass
        """).fetchone()
    num_parts: int = int(row[0]) if row else 0
    _record(
        "audit_log has >= 6 partitions",
        num_parts >= 6,
        f"got: {num_parts}",
    )

    # Partition names follow pattern audit_log_YYYY_MM
    part_rows = conn.execute("""
        SELECT c.relname
        FROM pg_inherits i
        JOIN pg_class c ON c.oid = i.inhrelid
        JOIN pg_class p ON p.oid = i.inhparent
        JOIN pg_namespace n ON n.oid = p.relnamespace
        WHERE n.nspname = 'theeyebeta' AND p.relname = 'audit_log'
        ORDER BY c.relname
        """).fetchall()
    part_names = [r[0] for r in part_rows]
    pattern = re.compile(r"^audit_log_\d{4}_\d{2}$")
    bad = [n for n in part_names if not pattern.match(n)]
    _record(
        "All partition names match audit_log_YYYY_MM",
        not bad,
        f"bad names: {bad}" if bad else f"sample: {part_names[:4]}",
    )

    # Function ensure_audit_partitions(int) exists
    row = conn.execute("""
        SELECT 1 FROM pg_proc p
        JOIN pg_namespace n ON n.oid = p.pronamespace
        WHERE n.nspname = 'theeyebeta' AND p.proname = 'ensure_audit_partitions'
        """).fetchone()
    fn_exists = row is not None
    _record("Function ensure_audit_partitions(int) exists", fn_exists)

    # Runs successfully with 0
    if fn_exists:
        try:
            conn.execute("SELECT theeyebeta.ensure_audit_partitions(0)")
            _record("ensure_audit_partitions(0) runs without error", True)
        except Exception as exc:
            _record("ensure_audit_partitions(0) runs without error", False, str(exc))

    _section_summary(8)


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 9 — Views & Functions
# ─────────────────────────────────────────────────────────────────────────────


def section_9(conn: psycopg.Connection[Any]) -> None:
    """Verify required views and stored functions exist."""
    _section(9, "Views & Functions")

    # View system_audit_summary exists
    row = conn.execute("""
        SELECT 1 FROM information_schema.views
        WHERE table_schema = 'theeyebeta' AND table_name = 'system_audit_summary'
        """).fetchone()
    view_exists = row is not None
    _record("View 'theeyebeta.system_audit_summary' exists", view_exists)

    # View has expected columns
    expected_view_cols = {
        "id",
        "ts",
        "actor",
        "action",
        "entity_type",
        "entity_id_safe",
        "payload_summary",
    }
    if view_exists:
        col_rows = conn.execute("""
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema='theeyebeta' AND table_name='system_audit_summary'
            """).fetchall()
        actual_view_cols = {r[0] for r in col_rows}
        missing = expected_view_cols - actual_view_cols
        _record(
            "system_audit_summary has all 7 expected columns",
            not missing,
            f"missing: {missing}" if missing else f"cols: {sorted(actual_view_cols)}",
        )
    else:
        _record("system_audit_summary has all 7 expected columns", False, "view not found")

    # Functions
    for fn_name in ("expire_stale_proposals", "ensure_audit_partitions"):
        row = conn.execute(
            """
            SELECT prorettype::regtype::text
            FROM pg_proc p
            JOIN pg_namespace n ON n.oid = p.pronamespace
            WHERE n.nspname = 'theeyebeta' AND p.proname = %s
            """,
            (fn_name,),
        ).fetchone()
        ok = row is not None and row[0] == "void"
        _record(
            f"Function '{fn_name}' exists and returns void",
            ok,
            f"returns: {row[0] if row else 'NOT FOUND'}",
        )

    _section_summary(9)


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 10 — Privilege Boundary Tests
# ─────────────────────────────────────────────────────────────────────────────


def section_10(superconn: psycopg.Connection[Any]) -> None:
    """Execute live privilege tests as tb_app and tb_rnd_readonly.

    All test rows are cleaned up via *superconn* in a finally block even on
    failure.
    """
    _section(10, "Privilege Boundary Tests (LIVE, as the actual roles)")

    cleanup_ids: list[tuple[str, str, Any]] = []  # (table, pk_col, pk_value)

    def _try(
        conn: psycopg.Connection[Any],
        sql: str,
        params: tuple[Any, ...] = (),
        *,
        expect_denied: bool = False,
        label: str,
    ) -> Any:  # noqa: ANN401 — return is row tuple or None; narrowing here adds no value
        """Execute *sql* and record pass/fail.

        Returns the first row fetched on success, None otherwise.
        """
        try:
            cur = conn.execute(sql, params)
            result = cur.fetchone() if cur.description else None
            if expect_denied:
                _record(label, False, "succeeded — expected InsufficientPrivilege")
            else:
                _record(label, True)
            return result
        except psycopg.errors.InsufficientPrivilege:
            if expect_denied:
                _record(label, True)
            else:
                _record(label, False, "InsufficientPrivilege — should have succeeded")
            return None
        except Exception as exc:
            _record(label, False, f"unexpected error: {exc}")
            return None

    try:
        # ── tb_app ────────────────────────────────────────────────────────────
        with _conn(_app_url()) as app:
            # SELECT audit_log
            _try(
                app,
                "SELECT id FROM theeyebeta.audit_log LIMIT 1",
                label="tb_app: SELECT from audit_log allowed",
            )

            # INSERT audit_log
            test_hash = os.urandom(32)
            row = _try(
                app,
                """
                INSERT INTO theeyebeta.audit_log
                    (actor, action, entity_type, entity_id, payload, row_hash)
                VALUES ('__verify__', 'test', '__verify__', %s, '{}'::jsonb, %s)
                RETURNING id
                """,
                (str(uuid.uuid4()), test_hash),
                label="tb_app: INSERT into audit_log allowed",
            )
            if row is not None:
                cleanup_ids.append(("audit_log", "id", row[0]))

            # UPDATE audit_log — must be denied
            _try(
                app,
                "UPDATE theeyebeta.audit_log SET actor='hack' WHERE false",
                expect_denied=True,
                label="tb_app: UPDATE on audit_log denied",
            )

            # DELETE audit_log — must be denied
            _try(
                app,
                "DELETE FROM theeyebeta.audit_log WHERE false",
                expect_denied=True,
                label="tb_app: DELETE on audit_log denied",
            )

            # INSERT proposals
            row = _try(
                app,
                """
                INSERT INTO theeyebeta.proposals
                    (proposed_by, category, target,
                     current_value, proposed_value, rationale, evidence)
                VALUES ('__verify__', 'architecture', '__verify__',
                        '{}'::jsonb, '{}'::jsonb, '__verify__', '{}'::jsonb)
                RETURNING id
                """,
                label="tb_app: INSERT into proposals allowed",
            )
            app_prop_id: Any = row[0] if row else None
            if app_prop_id is not None:
                cleanup_ids.append(("proposals", "id", app_prop_id))

            # UPDATE proposals
            if app_prop_id is not None:
                _try(
                    app,
                    "UPDATE theeyebeta.proposals SET status='approved' WHERE id=%s",
                    (app_prop_id,),
                    label="tb_app: UPDATE proposals allowed",
                )
            else:
                _record("tb_app: UPDATE proposals allowed", False, "no test row inserted")

            # DELETE proposals — create a dedicated row so we can delete it
            row2 = _try(
                app,
                """
                INSERT INTO theeyebeta.proposals
                    (proposed_by, category, target,
                     current_value, proposed_value, rationale, evidence)
                VALUES ('__verify_del__', 'architecture', '__verify__',
                        '{}'::jsonb, '{}'::jsonb, '__verify__', '{}'::jsonb)
                RETURNING id
                """,
                label="tb_app: INSERT temp proposals row for DELETE test",
            )
            if row2 is not None:
                try:
                    app.execute("DELETE FROM theeyebeta.proposals WHERE id=%s", (row2[0],))
                    _record("tb_app: DELETE from proposals allowed", True)
                except psycopg.errors.InsufficientPrivilege:
                    _record("tb_app: DELETE from proposals allowed", False, "InsufficientPrivilege")
                    cleanup_ids.append(("proposals", "id", row2[0]))
                except Exception as exc:
                    _record("tb_app: DELETE from proposals allowed", False, str(exc))
                    cleanup_ids.append(("proposals", "id", row2[0]))
            else:
                _record("tb_app: DELETE from proposals allowed", False, "could not create temp row")

            # SELECT every base table
            denied_tables: list[str] = []
            for table in EXPECTED_TABLES:
                if table == "audit_log":
                    continue  # already tested
                try:
                    app.execute(f"SELECT 1 FROM theeyebeta.{table} LIMIT 1")  # noqa: S608 — table name from EXPECTED_TABLES constant, not user input
                except psycopg.errors.InsufficientPrivilege:
                    denied_tables.append(table)
                except Exception:  # noqa: S110 — non-privilege errors (empty table, etc.) are benign in this probe
                    pass
            _record(
                "tb_app: SELECT from every base table allowed",
                not denied_tables,
                f"denied on: {denied_tables}" if denied_tables else "",
            )

        # ── tb_rnd_readonly ───────────────────────────────────────────────────
        with _conn(_rnd_url()) as rnd:
            # SELECT audit_log — must be denied
            _try(
                rnd,
                "SELECT id FROM theeyebeta.audit_log LIMIT 1",
                expect_denied=True,
                label="tb_rnd_readonly: SELECT from audit_log denied",
            )

            # SELECT system_audit_summary — must be allowed
            _try(
                rnd,
                "SELECT id FROM theeyebeta.system_audit_summary LIMIT 1",
                label="tb_rnd_readonly: SELECT from system_audit_summary allowed",
            )

            # INSERT proposals — must be allowed
            row = _try(
                rnd,
                """
                INSERT INTO theeyebeta.proposals
                    (proposed_by, category, target,
                     current_value, proposed_value, rationale, evidence)
                VALUES ('__verify_rnd__', 'architecture', '__verify_rnd__',
                        '{}'::jsonb, '{}'::jsonb, '__verify_rnd__', '{}'::jsonb)
                RETURNING id
                """,
                label="tb_rnd_readonly: INSERT into proposals allowed",
            )
            rnd_prop_id: Any = row[0] if row else None
            if rnd_prop_id is not None:
                cleanup_ids.append(("proposals", "id", rnd_prop_id))

            # UPDATE proposals — must be denied
            _try(
                rnd,
                "UPDATE theeyebeta.proposals SET status='applied' WHERE false",
                expect_denied=True,
                label="tb_rnd_readonly: UPDATE proposals denied",
            )

            # DELETE proposals — must be denied
            _try(
                rnd,
                "DELETE FROM theeyebeta.proposals WHERE false",
                expect_denied=True,
                label="tb_rnd_readonly: DELETE from proposals denied",
            )

            # SELECT from research/analysis tables
            for table in [
                "agent_decisions",
                "agent_runs",
                "guard_violations",
                "backtest_runs",
                "backtest_results",
            ]:
                _try(
                    rnd,
                    f"SELECT 1 FROM theeyebeta.{table} LIMIT 1",  # noqa: S608 — table name from hardcoded list, not user input
                    label=f"tb_rnd_readonly: SELECT from {table} allowed",
                )

            # INSERT agent_decisions — must be denied
            _try(
                rnd,
                """
                INSERT INTO theeyebeta.agent_decisions
                    (run_id, decision, confidence, rationale, evidence)
                VALUES (gen_random_uuid(), 'HOLD', 0.5, 'test', '{}'::jsonb)
                """,
                expect_denied=True,
                label="tb_rnd_readonly: INSERT into agent_decisions denied",
            )

    finally:
        for table, pk_col, pk_val in cleanup_ids:
            try:
                superconn.execute(
                    f"DELETE FROM theeyebeta.{table} WHERE {pk_col}=%s",  # noqa: S608 — table/col from hardcoded cleanup_ids list, not user input
                    (pk_val,),
                )
            except Exception as exc:
                print(
                    f"  [WARN] Cleanup failed for {table}.{pk_col}={pk_val}: {exc}",
                    flush=True,
                )

    _section_summary(10)


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 11 — Seed Data Sanity
# ─────────────────────────────────────────────────────────────────────────────


def section_11(conn: psycopg.Connection[Any]) -> None:
    """Verify seed data is present and correct."""
    _section(11, "Seed Data Sanity")

    # Exactly 7 exchanges
    row = conn.execute("SELECT count(*) FROM theeyebeta.exchanges").fetchone()
    ex_count: int = int(row[0]) if row else 0
    _record("Exactly 7 exchanges", ex_count == 7, f"got: {ex_count}")

    # Codes match expected set
    code_rows = conn.execute("SELECT code FROM theeyebeta.exchanges ORDER BY code").fetchall()
    actual_codes = {r[0] for r in code_rows}
    expected_codes = {"XNAS", "XNYS", "XSHG", "XSHE", "XTAI", "XTKS", "XHKG"}
    missing = expected_codes - actual_codes
    extra = actual_codes - expected_codes
    _record(
        "Exchange codes = {XNAS,XNYS,XSHG,XSHE,XTAI,XTKS,XHKG}",
        not missing and not extra,
        (f"missing: {missing}" if missing else "") + (f" extra: {extra}" if extra else ""),
    )

    # Each exchange has non-null timezone and 3-char currency_iso
    bad_rows = conn.execute("""
        SELECT code FROM theeyebeta.exchanges
        WHERE timezone IS NULL OR length(currency_iso) != 3
        """).fetchall()
    _record(
        "All exchanges have non-null timezone and 3-char currency_iso",
        not bad_rows,
        f"violations: {[r[0] for r in bad_rows]}" if bad_rows else "",
    )

    # Strategy 'example_swing_us' exists
    row = conn.execute("SELECT 1 FROM theeyebeta.strategies WHERE id='example_swing_us'").fetchone()
    _record("Strategy 'example_swing_us' exists", row is not None)

    _section_summary(11)


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 12 — Cross-Cluster Integrity
# ─────────────────────────────────────────────────────────────────────────────


def section_12(conn: psycopg.Connection[Any]) -> None:
    """Verify schema ownership, table placement, and dropped artefacts.

    This DB instance hosts an independent legacy platform in the public schema
    (96 GB, entirely different table schemas). Checks are scoped to theeyebeta-
    specific invariants only, never assuming exclusive ownership of the instance.
    """
    _section(12, "Cross-Cluster Integrity")

    # theeyebeta.alembic_version exists with the correct revision.
    # public.alembic_version may also exist (belonging to the legacy platform)
    # and is irrelevant to this check.
    row = conn.execute("""
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'theeyebeta' AND table_name = 'alembic_version'
        """).fetchone()
    _record(
        "alembic_version table exists in schema 'theeyebeta'",
        row is not None,
        "missing" if row is None else "",
    )

    # No theeyebeta-SPECIFIC table names appear in any other schema.
    # Uses names unique to this platform (agent/guard/proposal/audit terminology)
    # rather than generic market-data names (signals, exchanges, etc.) that any
    # independent system sharing this instance might legitimately also use.
    unique_names = [
        "agents",
        "agent_runs",
        "agent_decisions",
        "agent_messages",
        "agent_memory",
        "guard_violations",
        "proposals",
        "audit_log",
    ]
    wrong_schema_rows = conn.execute(
        """
        SELECT table_schema, table_name
        FROM information_schema.tables
        WHERE table_name = ANY(%s)
          AND table_schema != 'theeyebeta'
          AND table_type = 'BASE TABLE'
        """,
        (unique_names,),
    ).fetchall()
    _record(
        "No theeyebeta-specific tables leak into other schemas",
        not wrong_schema_rows,
        (
            f"found elsewhere: {[(r[0], r[1]) for r in wrong_schema_rows]}"
            if wrong_schema_rows
            else ""
        ),  # noqa: E501
    )

    # _audit_summary_placeholder was dropped (does not exist anywhere)
    placeholder_rows = conn.execute("""
        SELECT table_schema FROM information_schema.tables
        WHERE table_name = '_audit_summary_placeholder'
        """).fetchall()
    _record(
        "_audit_summary_placeholder does not exist anywhere",
        not placeholder_rows,
        f"found in: {[r[0] for r in placeholder_rows]}" if placeholder_rows else "",
    )

    _section_summary(12)


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

_BANNER_WIDTH = 63


def main() -> None:
    """Entry point: run all sections then print a summary."""
    if not DATABASE_URL:
        print("ERROR: DATABASE_URL is not set.", file=sys.stderr)
        sys.exit(1)
    if not TB_APP_PASSWORD:
        print("ERROR: TB_APP_PASSWORD is not set.", file=sys.stderr)
        sys.exit(1)
    if not TB_RND_PASSWORD:
        print("ERROR: TB_RND_PASSWORD is not set.", file=sys.stderr)
        sys.exit(1)

    print("═" * _BANNER_WIDTH)
    print("  theeyebeta — Full Database Verification")
    print("═" * _BANNER_WIDTH, flush=True)

    try:
        with _conn() as conn:
            section_1(conn)
            section_2(conn)
            section_3(conn)
            section_4(conn)
            section_5(conn)
            section_6(conn)
            section_7(conn)
            section_8(conn)
            section_9(conn)
            section_10(conn)  # opens its own sub-connections internally
            section_11(conn)
            section_12(conn)
    except psycopg.OperationalError as exc:
        print(f"\n  {CROSS} Failed to connect to database: {exc}", file=sys.stderr)
        sys.exit(1)

    # ── Summary ───────────────────────────────────────────────────────────────
    total_passed = sum(1 for _, _, p, _ in _results if p)
    total_checks = len(_results)
    all_pass = total_passed == total_checks

    print("\n" + "═" * _BANNER_WIDTH)

    # Per-section breakdown — 4 per row
    parts: list[str] = []
    for s in sorted(_section_counts):
        p, t = _section_counts[s]
        cfn = _green if p == t else _red
        parts.append(f"SECTION {s}: {cfn(f'{p}/{t}')}")
    for i in range(0, len(parts), 4):
        print("  " + "   ".join(parts[i : i + 4]))

    print()
    summary_cfn = _green if all_pass else _red
    print(f"  {_bold('SUMMARY:')} {summary_cfn(f'{total_passed}/{total_checks} checks passed')}")
    print("═" * _BANNER_WIDTH)

    sys.exit(0 if all_pass else 1)


if __name__ == "__main__":
    main()
