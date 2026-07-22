#!/bin/sh
set -eu

migration_name="20260721_structured_ticket_closeout.sql"
migration_path="/migrations/${migration_name}"
postgres_password_file="/run/secrets/postgres_superuser_password"

if [ ! -r "$postgres_password_file" ]; then
    echo "Required PostgreSQL superuser secret is missing: $postgres_password_file" >&2
    exit 1
fi

export PGPASSWORD
PGPASSWORD=$(cat "$postgres_password_file")

if [ ! -f "$migration_path" ]; then
    echo "Required CRM migration is missing: $migration_path" >&2
    exit 1
fi

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
    echo "CRM base schema is stale or incomplete; refusing ${migration_name}. Apply the workspace-schema upgrade before closeout migration." >&2
    exit 1
fi

psql -v ON_ERROR_STOP=1 <<'SQL'
CREATE TABLE IF NOT EXISTS schema_migrations (
    name TEXT PRIMARY KEY,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
SQL

if psql -Atqc "SELECT 1 FROM schema_migrations WHERE name = '${migration_name}'" | grep -qx '1'; then
    echo "CRM migration ${migration_name} is already recorded."
    exit 0
fi

existing_tables=$(psql -Atqc "
    SELECT count(*)
    FROM (VALUES
        ('ticket_closeouts'),
        ('ticket_closeout_line_items'),
        ('ticket_closeout_profile_updates'),
        ('future_service_plans'),
        ('ticket_closeout_follow_up_actions')
    ) AS expected(name)
    WHERE to_regclass('public.' || name) IS NOT NULL
")

case "$existing_tables" in
    5)
        echo "CRM closeout schema already exists; recording ${migration_name}."
        ;;
    0)
        echo "Applying CRM migration ${migration_name}."
        psql -v ON_ERROR_STOP=1 -f "$migration_path"
        ;;
    *)
        echo "CRM closeout schema is partially present (${existing_tables}/5 tables); refusing migration." >&2
        exit 1
        ;;
esac

psql -v ON_ERROR_STOP=1 -c "INSERT INTO schema_migrations (name) VALUES ('${migration_name}')"
echo "CRM migration ${migration_name} recorded."
