-- Admin SQL router integration seed.
--
-- A simple sandbox table used by both /query (SELECT) and /execute (UPDATE)
-- tests. Lives in the public ``theeyebeta`` schema and is granted to
-- ``tb_app`` (which is the role the admin-service connects as).

CREATE TABLE IF NOT EXISTS theeyebeta.admin_sql_sandbox (
    id    int PRIMARY KEY,
    label text NOT NULL,
    value int NOT NULL DEFAULT 0
);

GRANT SELECT, INSERT, UPDATE, DELETE
   ON theeyebeta.admin_sql_sandbox TO tb_app;

INSERT INTO theeyebeta.admin_sql_sandbox (id, label, value)
VALUES
    (1, 'alpha', 10),
    (2, 'bravo', 20),
    (3, 'charlie', 30)
ON CONFLICT (id) DO UPDATE
   SET label = EXCLUDED.label,
       value = EXCLUDED.value;
