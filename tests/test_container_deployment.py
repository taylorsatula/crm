"""Static contracts for the CRM container appliance."""

from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text()


def test_compose_keeps_crm_private_and_state_isolated() -> None:
    compose = _read("compose.yaml")

    assert compose.startswith("name: crm\n")
    assert "${CRM_HOST_BIND:-127.0.0.1}:${CRM_HOST_PORT:-8000}:8000" in compose
    assert "crm_postgres_data" in compose
    assert "crm_vault_data" in compose
    assert "crm_approle_data" in compose
    assert "postgres_data:/var/lib/postgresql/data" in compose
    assert "vault_data:/vault/state" in compose
    assert "VAULT_ADDR=http://127.0.0.1:8200 vault status" in compose
    assert "./schema.sql:/opt/crm/schema.sql:ro" in compose
    assert "\\i /opt/crm/schema.sql" in _read("deploy/docker/postgres-init/20-schema.sql")
    assert "source: crm_postgres_superuser_password" in compose
    assert "source: crm_lifecycle_service_secret" in compose
    bootstrap_block = compose.split("  vault_bootstrap:", 1)[1].split("\nsecrets:", 1)[0]
    assert "approle_data:/vault/approle" in bootstrap_block
    assert "CRM_LIFECYCLE_SECRET_FILE" in compose


def test_vault_bootstrap_scopes_crm_secrets_and_preserves_partial_state() -> None:
    bootstrap = _read("deploy/docker/vault-bootstrap.sh")

    assert 'path "secret/data/crm/*"' in bootstrap
    assert "Partial Vault initialization exists" in bootstrap
    assert "refusing to overwrite existing state" in bootstrap
    assert "rm -rf" not in bootstrap
    assert "crm-bootstrap-complete" in bootstrap
    assert "publish_approle_credentials" in bootstrap
    assert "chown 100:1000" in bootstrap


def test_container_entrypoints_parse() -> None:
    completed = subprocess.run(
        [
            "sh",
            "-n",
            "deploy/docker/entrypoint.sh",
            "deploy/docker/vault-bootstrap.sh",
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
