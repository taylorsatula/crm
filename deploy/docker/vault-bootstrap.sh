#!/bin/sh
set -eu
umask 077

state_dir=/vault/state
approle_dir=/vault/approle
init_keys_file="${state_dir}/init-keys.json"
pending_init_keys_file="${init_keys_file}.pending"
bootstrap_marker="${state_dir}/crm-bootstrap-complete"

read_secret() {
    name="$1"
    secret_file="/run/secrets/${name}"
    if [ ! -s "$secret_file" ]; then
        echo "Required Docker secret is missing or empty: ${name}" >&2
        exit 1
    fi
    tr -d '\r\n' < "$secret_file"
}

prepare_vault_storage() {
    mkdir -p "$state_dir"
    chown 100:1000 "$state_dir"
    chmod 700 "$state_dir"
}

wait_for_postgres() {
    postgres_password=$(read_secret postgres_superuser_password)
    export PGPASSWORD="$postgres_password"
    until psql --host postgres --username postgres --dbname crm --command 'SELECT 1' >/dev/null 2>&1; do
        echo "Waiting for CRM PostgreSQL..." >&2
        sleep 1
    done
}

wait_for_vault() {
    while true; do
        if vault status >/dev/null 2>&1; then
            status=0
        else
            status=$?
        fi
        if [ "$status" -eq 0 ] || [ "$status" -eq 2 ]; then
            return
        fi
        echo "Waiting for CRM Vault..." >&2
        sleep 1
    done
}

initialize_vault() {
    if [ -f "$init_keys_file" ]; then
        return
    fi
    if [ -e "$pending_init_keys_file" ]; then
        echo "Partial Vault initialization exists at ${pending_init_keys_file}; refusing to overwrite it." >&2
        exit 1
    fi

    vault operator init -key-shares=1 -key-threshold=1 -format=json > "$pending_init_keys_file"
    mv "$pending_init_keys_file" "$init_keys_file"
}

unseal_and_authenticate() {
    unseal_key=$(jq -r '.unseal_keys_b64[0]' < "$init_keys_file")
    root_token=$(jq -r '.root_token' < "$init_keys_file")
    if vault status >/dev/null 2>&1; then
        status=0
    else
        status=$?
    fi
    if [ "$status" -eq 2 ]; then
        vault operator unseal "$unseal_key" >/dev/null
    elif [ "$status" -ne 0 ]; then
        echo "Vault is unavailable while attempting to unseal it." >&2
        exit 1
    fi
    export VAULT_TOKEN="$root_token"
}

configure_approle() {
    vault secrets list | grep -q '^secret/' || vault secrets enable -path=secret -version=2 kv
    vault auth list | grep -q '^approle/' || vault auth enable approle
    vault policy write crm-policy - <<'EOF'
path "secret/data/crm/*" {
  capabilities = ["read"]
}
path "secret/metadata/crm/*" {
  capabilities = ["list", "read"]
}
EOF
    vault write auth/approle/role/crm policies=crm-policy token_ttl=1h token_max_ttl=4h >/dev/null
}

publish_approle_credentials() {
    mkdir -p "$approle_dir"
    vault read -field=role_id auth/approle/role/crm/role-id > "${approle_dir}/crm-role-id.txt"
    if [ ! -s "${approle_dir}/crm-secret-id.txt" ]; then
        vault write -field=secret_id -f auth/approle/role/crm/secret-id > "${approle_dir}/crm-secret-id.txt"
    fi
    chown 10001:10001 "${approle_dir}/crm-role-id.txt" "${approle_dir}/crm-secret-id.txt"
    chmod 600 "${approle_dir}/crm-role-id.txt" "${approle_dir}/crm-secret-id.txt"
}

bootstrap_crm_secrets() {
    if [ -e "$bootstrap_marker" ]; then
        return
    fi
    if vault kv get secret/crm/database >/dev/null 2>&1; then
        echo "CRM Vault has database secrets without a bootstrap marker; refusing to overwrite existing state." >&2
        exit 1
    fi

    admin_password=$(openssl rand -hex 32)
    dbuser_password=$(openssl rand -hex 32)
    lifecycle_secret=$(read_secret crm_lifecycle_service_secret)
    email_api_key=$(read_secret email_gateway_api_key)
    email_hmac_secret=$(read_secret email_gateway_hmac_secret)
    llm_api_key=$(read_secret llm_api_key)

    psql --host postgres --username postgres --dbname crm --set ON_ERROR_STOP=1 \
        --command "ALTER ROLE crm_admin WITH PASSWORD '${admin_password}'; ALTER ROLE crm_dbuser WITH PASSWORD '${dbuser_password}';"

    vault kv put secret/crm/database \
        url="postgresql://crm_dbuser:${dbuser_password}@postgres:5432/crm" \
        admin_url="postgresql://crm_admin:${admin_password}@postgres:5432/crm"
    vault kv put secret/crm/lifecycle service_secret="$lifecycle_secret"
    vault kv put secret/crm/email \
        gateway_url="$CRM_EMAIL_GATEWAY_URL" \
        api_key="$email_api_key" \
        hmac_secret="$email_hmac_secret" \
        health_url="$CRM_EMAIL_HEALTH_URL"
    vault kv put secret/crm/llm \
        api_key="$llm_api_key" \
        base_url="$CRM_LLM_BASE_URL" \
        model="$CRM_LLM_MODEL"

    touch "${bootstrap_marker}.pending"
    mv "${bootstrap_marker}.pending" "$bootstrap_marker"
}

prepare_vault_storage
wait_for_postgres
wait_for_vault
initialize_vault
unseal_and_authenticate
configure_approle
bootstrap_crm_secrets
publish_approle_credentials

while true; do
    wait_for_vault
    unseal_and_authenticate
    sleep 5
done
