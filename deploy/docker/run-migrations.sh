#!/bin/sh
set -eu

# Applies every unapplied migration in /migrations in lexicographic order.
# Each migration file is self-contained (own BEGIN/COMMIT) and idempotence is
# tracked in schema_migrations: an applied migration is recorded and skipped.
postgres_password_file="/run/secrets/postgres_superuser_password"

if [ ! -r "$postgres_password_file" ]; then
    echo "Required PostgreSQL superuser secret is missing: $postgres_password_file" >&2
    exit 1
fi

export PGPASSWORD
PGPASSWORD=$(cat "$postgres_password_file")

base_tables=$(psql -Atqc "
    SELECT count(*)
    FROM (VALUES
        ('workspaces'),
        ('customers'),
        ('addresses'),
        ('tickets'),
        ('line_items')
    ) AS expected(name)
    WHERE to_regclass('public.' || name) IS NOT NULL
")

if [ "$base_tables" -ne 5 ] || ! psql -Atqc \
    "SELECT to_regprocedure('public.update_updated_at_column()') IS NOT NULL" | grep -qx 't'; then
    echo "CRM base schema is stale or incomplete; refusing migrations until the workspace-schema upgrade is applied." >&2
    exit 1
fi

psql -v ON_ERROR_STOP=1 <<'SQL'
CREATE TABLE IF NOT EXISTS schema_migrations (
    name TEXT PRIMARY KEY,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
SQL

for migration_path in $(ls /migrations/*.sql | LC_ALL=C sort); do
    migration_name=$(basename "$migration_path")

    if psql -Atqc "SELECT 1 FROM schema_migrations WHERE name = '${migration_name}'" | grep -qx '1'; then
        echo "CRM migration ${migration_name} is already recorded."
        continue
    fi

    echo "Applying CRM migration ${migration_name}."
    psql -v ON_ERROR_STOP=1 -f "$migration_path"
    psql -v ON_ERROR_STOP=1 -c "INSERT INTO schema_migrations (name) VALUES ('${migration_name}')"
    echo "CRM migration ${migration_name} recorded."
done
