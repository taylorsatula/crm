"""Tests for project packaging metadata."""

import re
import tomllib
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _dependency_name(requirement: str) -> str:
    return re.split(r"[<>=!~; ]", requirement, maxsplit=1)[0].lower()


def test_pyproject_is_the_dependency_manifest():
    manifest = PROJECT_ROOT / "pyproject.toml"

    assert manifest.exists(), "pyproject.toml must be the project dependency manifest"


def test_pyproject_requires_python_312_or_newer():
    data = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text())

    assert data["project"]["requires-python"] == ">=3.12"


def test_pyproject_declares_runtime_dependencies():
    data = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text())
    dependencies = {_dependency_name(dep) for dep in data["project"]["dependencies"]}

    assert {
        "fastapi",
        "uvicorn",
        "pydantic[email]",
        "psycopg[binary]",
        "psycopg-pool",
        "redis",
        "hvac",
        "requests",
        "anthropic",
        "json-repair",
        "python-dotenv",
    }.issubset(dependencies)


def test_pyproject_declares_test_dependencies():
    data = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text())
    test_dependencies = {
        _dependency_name(dep)
        for dep in data["project"]["optional-dependencies"]["dev"]
    }

    assert {"pytest", "responses"}.issubset(test_dependencies)


def test_pyproject_configures_pytest_testpaths():
    data = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text())

    assert data["tool"]["pytest"]["ini_options"]["testpaths"] == ["tests"]
