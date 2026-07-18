# CRM Docker bootstrap secrets

Create these extensionless files before the first `docker compose up`:

- `postgres_superuser_password` — a new random password for the isolated CRM PostgreSQL superuser.
- `crm_lifecycle_service_secret` — the secret MIRA uses to call CRM lifecycle routes; it must match MIRA's `crm_lifecycle_service_secret` exactly. Set `CRM_LIFECYCLE_SECRET_FILE` to this file.
- `email_gateway_api_key`
- `email_gateway_hmac_secret`
- `llm_api_key`

Each file must contain exactly one value. They are excluded from Git and the
Docker build context. On first boot they provision CRM-only Vault records; the
running CRM receives only its generated AppRole credentials from the private
`crm_vault_data` volume.
