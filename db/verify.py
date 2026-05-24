"""
Architectural invariant verification for theeyebeta.
Prints PASS/FAIL for each check and exits 0 only if all pass.
"""
import os
import sys
import psycopg

DATABASE_URL = os.environ["DATABASE_URL"].replace("+psycopg", "")
TB_APP_PASSWORD = os.environ["TB_APP_PASSWORD"]
TB_RND_PASSWORD = os.environ["TB_RND_PASSWORD"]

PASS = "\u2713"
FAIL = "\u2717"

results: list[bool] = []


def check(name: str, passed: bool, detail: str = "") -> None:
    mark = PASS if passed else FAIL
    suffix = f"  ({detail})" if detail else ""
    print(f"  {mark}  {name}{suffix}")
    results.append(passed)


def _conn(url: str = DATABASE_URL, **kwargs: object) -> psycopg.Connection:  # type: ignore[type-arg]
    return psycopg.connect(url, autocommit=True, **kwargs)  # type: ignore[call-arg]


def _rnd_url() -> str:
    import urllib.parse as up
    p = up.urlparse(DATABASE_URL)
    return p._replace(
        netloc=f"tb_rnd_readonly:{TB_RND_PASSWORD}@{p.hostname}:{p.port or 5432}"
    ).geturl()


def _app_url() -> str:
    import urllib.parse as up
    p = up.urlparse(DATABASE_URL)
    return p._replace(
        netloc=f"tb_app:{TB_APP_PASSWORD}@{p.hostname}:{p.port or 5432}"
    ).geturl()


def run_checks() -> None:
    with _conn() as conn:
        # ── a. Schema exists ────────────────────────────────────────────────
        row = conn.execute(
            "SELECT 1 FROM pg_namespace WHERE nspname='theeyebeta'"
        ).fetchone()
        check("a. schema theeyebeta exists", row is not None)

        # ── b. All 10 migrations applied ────────────────────────────────────
        row = conn.execute(
            "SELECT version_num FROM theeyebeta.alembic_version"
        ).fetchone()
        expected_rev = "0009_audit"
        ok = row is not None and row[0] == expected_rev
        check("b. migrations at head (0009_audit)", ok, f"got {row[0] if row else None}")

        # ── c. Table counts ─────────────────────────────────────────────────
        total = conn.execute(
            """SELECT count(*) FROM information_schema.tables
               WHERE table_schema='theeyebeta' AND table_type='BASE TABLE'"""
        ).fetchone()[0]
        check("c. total BASE TABLE count ≥ 40", total >= 40, f"got {total}")

        # Count partition parents separately (excludes partitions themselves)
        parents = conn.execute(
            """SELECT count(*) FROM pg_class c
               JOIN pg_namespace n ON n.oid=c.relnamespace
               WHERE n.nspname='theeyebeta'
                 AND c.relkind IN ('r','p')
                 AND NOT EXISTS (
                   SELECT 1 FROM pg_inherits WHERE inhrelid=c.oid
                 )"""
        ).fetchone()[0]
        check("c. distinct parent tables ≥ 30", parents >= 30, f"got {parents}")

        # ── d. Hypertables ───────────────────────────────────────────────────
        ht = conn.execute(
            """SELECT count(*) FROM timescaledb_information.hypertables
               WHERE hypertable_schema='theeyebeta'"""
        ).fetchone()[0]
        check("d. hypertables = 5", ht == 5, f"got {ht}")

        # ── e. Roles exist ───────────────────────────────────────────────────
        for role in ("tb_app", "tb_rnd_readonly"):
            row = conn.execute(
                "SELECT 1 FROM pg_roles WHERE rolname=%s", (role,)
            ).fetchone()
            check(f"e. role {role} exists", row is not None)

        # ── j. audit_log partitions ──────────────────────────────────────────
        parts = conn.execute(
            """SELECT count(*) FROM pg_inherits
               WHERE inhparent='theeyebeta.audit_log'::regclass"""
        ).fetchone()[0]
        # ensure_audit_partitions(6) loops FOR m IN 0..6 — 7 partitions inclusive
        check("j. audit_log partitions = 7", parts == 7, f"got {parts}")

        # ── k. HNSW vector indexes ────────────────────────────────────────────
        hnsw = conn.execute(
            """SELECT count(*) FROM pg_indexes
               WHERE schemaname='theeyebeta' AND indexname LIKE '%hnsw%'"""
        ).fetchone()[0]
        check("k. HNSW indexes = 2", hnsw == 2, f"got {hnsw}")

        # ── l. Seeds ─────────────────────────────────────────────────────────
        ex = conn.execute("SELECT count(*) FROM theeyebeta.exchanges").fetchone()[0]
        check("l. exchanges seed = 7", ex == 7, f"got {ex}")

        st = conn.execute("SELECT count(*) FROM theeyebeta.strategies").fetchone()[0]
        check("l. strategies seed ≥ 1", st >= 1, f"got {st}")

        # ── m. search_path db setting ────────────────────────────────────────
        rows = conn.execute(
            """SELECT s.setconfig
               FROM pg_db_role_setting s
               JOIN pg_database d ON d.oid = s.setdatabase
               WHERE d.datname = current_database()"""
        ).fetchall()
        cfg_vals = [v for row in rows for v in (row[0] or [])]
        has_sp = any("search_path" in v for v in cfg_vals)
        check("m. search_path set on database", has_sp, f"configs: {cfg_vals or 'none'}")

    # ── f. audit_log append-only for tb_app ────────────────────────────────
    try:
        with _conn(_app_url()) as aconn:
            aconn.execute("DELETE FROM theeyebeta.audit_log WHERE false")
        check("f. tb_app DELETE on audit_log blocked", False, "DELETE succeeded — should have failed")
    except psycopg.errors.InsufficientPrivilege:
        check("f. tb_app DELETE on audit_log blocked", True)
    except Exception as exc:
        check("f. tb_app DELETE on audit_log blocked", False, f"unexpected: {exc}")

    # ── g. tb_rnd_readonly cannot UPDATE proposals ─────────────────────────
    try:
        with _conn(_rnd_url()) as rconn:
            rconn.execute("UPDATE theeyebeta.proposals SET status='applied' WHERE false")
        check("g. tb_rnd_readonly UPDATE proposals blocked", False, "UPDATE succeeded — should have failed")
    except psycopg.errors.InsufficientPrivilege:
        check("g. tb_rnd_readonly UPDATE proposals blocked", True)
    except Exception as exc:
        check("g. tb_rnd_readonly UPDATE proposals blocked", False, f"unexpected: {exc}")

    # ── h. tb_rnd_readonly cannot read raw audit_log ───────────────────────
    try:
        with _conn(_rnd_url()) as rconn:
            rconn.execute("SELECT * FROM theeyebeta.audit_log LIMIT 1")
        check("h. tb_rnd_readonly SELECT audit_log blocked", False, "SELECT succeeded — should have failed")
    except psycopg.errors.InsufficientPrivilege:
        check("h. tb_rnd_readonly SELECT audit_log blocked", True)
    except Exception as exc:
        check("h. tb_rnd_readonly SELECT audit_log blocked", False, f"unexpected: {exc}")

    # ── i. tb_rnd_readonly CAN read sanitized view ─────────────────────────
    try:
        with _conn(_rnd_url()) as rconn:
            rconn.execute("SELECT * FROM theeyebeta.system_audit_summary LIMIT 1")
        check("i. tb_rnd_readonly SELECT system_audit_summary allowed", True)
    except psycopg.errors.InsufficientPrivilege:
        check("i. tb_rnd_readonly SELECT system_audit_summary allowed", False, "permission denied")
    except Exception as exc:
        check("i. tb_rnd_readonly SELECT system_audit_summary allowed", False, f"unexpected: {exc}")


if __name__ == "__main__":
    print(f"\nVerifying theeyebeta architectural invariants against {DATABASE_URL}\n")
    run_checks()
    total = len(results)
    passed = sum(results)
    failed = total - passed
    print(f"\n  {passed}/{total} checks passed", end="")
    if failed:
        print(f", {failed} FAILED")
        sys.exit(1)
    else:
        print(" — all good")
        sys.exit(0)
