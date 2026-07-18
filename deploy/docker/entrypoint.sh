#!/bin/sh
set -eu

approle_dir="${CRM_APPROLE_DIR:-/vault/approle}"
role_id_file="${approle_dir}/crm-role-id.txt"
secret_id_file="${approle_dir}/crm-secret-id.txt"

until [ -s "$role_id_file" ] && [ -s "$secret_id_file" ]; do
    echo "Waiting for CRM Vault AppRole bootstrap..." >&2
    sleep 1
done

export VAULT_ROLE_ID
export VAULT_SECRET_ID
VAULT_ROLE_ID=$(tr -d '\r\n' < "$role_id_file")
VAULT_SECRET_ID=$(tr -d '\r\n' < "$secret_id_file")

exec /opt/crm/.venv/bin/uvicorn main:app --host 0.0.0.0 --port 8000
