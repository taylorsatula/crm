# CRM container deployment

CRM is a private service. The Compose project starts an isolated PostgreSQL 16,
Vault, Vault bootstrap sidecar, and the CRM API. It does not publish Postgres or
Vault. The API binds to `127.0.0.1:8000` by default.

## First boot

1. Copy `.env.example` to `.env` and set the non-secret email/LLM endpoints.
2. Create the five files listed in
   [`deploy/docker/secrets/README.md`](../deploy/docker/secrets/README.md).
3. Start the appliance:

   ```bash
   docker compose --env-file .env up --build -d
   ```

4. Confirm that the process is live:

   ```bash
   curl http://127.0.0.1:8000/health/live
   ```

`/health/ready` additionally probes Vault, PostgreSQL, the configured email
gateway, and the configured LLM provider. It remains unhealthy when placeholder
gateway or LLM credentials are used; that is correct and does not mean the CRM
process failed to start.

## MIRA integration

When MIRA and CRM are joined to one Docker network, MIRA must use
`http://crm:8000` as its CRM base URL. Give both appliances the exact same
`crm_lifecycle_service_secret`; each stores its own copy in its separate Vault.

Keep CRM's host bind on `127.0.0.1` unless an intentional reverse proxy or
private network boundary is added. Do not publish its internal lifecycle API on
the public internet.

The `crm_postgres_data` and `crm_vault_data` named volumes are persistent state.
Upgrades use `docker compose up --build -d`; do not remove those volumes.
