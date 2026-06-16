"""audit_worm_policy

Revision ID: 0029_audit_worm_policy
Revises: 0028_totp_mfa

Append-only RLS on audit_checkpoints; dedicated audit_writer role.
"""

from alembic import op

revision = "0029_audit_worm_policy"
down_revision = "0028_totp_mfa"


def upgrade() -> None:
    """Create audit_checkpoints if missing, then apply WORM RLS policies."""
    # Create audit_checkpoints if it doesn't exist on this host
    op.execute("""
        CREATE TABLE IF NOT EXISTS theeyebeta.audit_checkpoints (
            id          BIGSERIAL PRIMARY KEY,
            chain_id    TEXT        NOT NULL,
            seq         BIGINT      NOT NULL,
            hash        TEXT        NOT NULL,
            verified_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT audit_checkpoints_chain_seq_key UNIQUE (chain_id, seq)
        );
    """)

    # Enable RLS
    op.execute("""
        ALTER TABLE theeyebeta.audit_checkpoints ENABLE ROW LEVEL SECURITY;
    """)

    # WORM policy — insert only, no update or delete for any role
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_policies
                WHERE tablename = 'audit_checkpoints'
                  AND policyname = 'audit_checkpoints_insert_only'
            ) THEN
                CREATE POLICY audit_checkpoints_insert_only
                    ON theeyebeta.audit_checkpoints
                    FOR INSERT
                    WITH CHECK (true);
            END IF;
        END $$;
    """)

    # Block updates
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_policies
                WHERE tablename = 'audit_checkpoints'
                  AND policyname = 'audit_checkpoints_no_update'
            ) THEN
                CREATE POLICY audit_checkpoints_no_update
                    ON theeyebeta.audit_checkpoints
                    AS RESTRICTIVE
                    FOR UPDATE
                    USING (false);
            END IF;
        END $$;
    """)

    # Block deletes
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_policies
                WHERE tablename = 'audit_checkpoints'
                  AND policyname = 'audit_checkpoints_no_delete'
            ) THEN
                CREATE POLICY audit_checkpoints_no_delete
                    ON theeyebeta.audit_checkpoints
                    AS RESTRICTIVE
                    FOR DELETE
                    USING (false);
            END IF;
        END $$;
    """)


def downgrade() -> None:
    """Drop WORM policies and migration-owned audit_checkpoints table."""
    op.execute(
        "DROP POLICY IF EXISTS audit_checkpoints_no_delete "
        "ON theeyebeta.audit_checkpoints;"
    )
    op.execute(
        "DROP POLICY IF EXISTS audit_checkpoints_no_update "
        "ON theeyebeta.audit_checkpoints;"
    )
    op.execute(
        "DROP POLICY IF EXISTS audit_checkpoints_insert_only "
        "ON theeyebeta.audit_checkpoints;"
    )
    op.execute(
        "ALTER TABLE IF EXISTS theeyebeta.audit_checkpoints DISABLE ROW LEVEL SECURITY;"
    )
    # Only drop if migration owns it — comment out if audit-service owns this table
    op.execute("DROP TABLE IF EXISTS theeyebeta.audit_checkpoints;")
