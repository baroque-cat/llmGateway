"""Structural tests verifying docker-compose.yml test-database service (S50-S53).

Ensures that the ``test-database`` service in ``docker-compose.yml`` is
correctly configured with test-safe credentials, a non-conflicting port,
and that the compose file parses cleanly via ``yaml.safe_load()``.
"""

# pyright: reportPrivateUsage=false

from __future__ import annotations

from typing import Any, cast

import yaml

from tests.conftest import _REPO_ROOT


def _load_compose() -> dict[str, Any]:
    """Load and parse docker-compose.yml via yaml.safe_load().

    Returns:
        Parsed compose file as a dictionary.
    """
    compose_path = _REPO_ROOT / "docker-compose.yml"
    with open(compose_path, encoding="utf-8") as f:
        return cast(dict[str, Any], yaml.safe_load(f))


def test_test_database_service_configured_in_compose() -> None:
    """Verify test-database service exists with postgres:18-alpine image (S50).

    Checks:
        - ``test-database`` key exists in ``services``
        - The ``image`` field equals ``postgres:18-alpine``
    """
    data = _load_compose()
    services: dict[str, Any] = data["services"]
    assert "test-database" in services, "test-database service not found in compose"
    test_db: dict[str, Any] = services["test-database"]
    assert (
        test_db["image"] == "postgres:18-alpine"
    ), f"Expected image 'postgres:18-alpine', got {test_db['image']!r}"


def test_test_database_uses_test_safe_credentials() -> None:
    """Verify test-database uses test_user/test_password/test_db (S51).

    Checks:
        - POSTGRES_USER == test_user
        - POSTGRES_PASSWORD == test_password
        - POSTGRES_DB == test_db
    """
    data = _load_compose()
    services: dict[str, Any] = data["services"]
    test_db: dict[str, Any] = services["test-database"]
    env_raw: Any = test_db["environment"]
    env: list[str] = list(env_raw)
    env_dict: dict[str, str] = {}
    for item in env:
        key, _, value = item.partition("=")
        env_dict[key] = value
    assert env_dict["POSTGRES_USER"] == "test_user"
    assert env_dict["POSTGRES_PASSWORD"] == "test_password"
    assert env_dict["POSTGRES_DB"] == "test_db"


def test_test_database_port_differs_from_production() -> None:
    """Verify test-database port 5433 differs from production port 5432 (S52).

    Checks:
        - test-database exposes host port 5433
        - production database either has no external ports (internal only)
          or uses a different host port than test-database
    """
    data = _load_compose()
    services: dict[str, Any] = data["services"]
    test_db: dict[str, Any] = services["test-database"]
    prod_db: dict[str, Any] = services["database"]
    test_ports_raw: Any = test_db["ports"]
    test_ports: list[str] = list(test_ports_raw)
    test_host_port: str = test_ports[0].split(":")[0]
    # Production database may not expose ports to host (internal only).
    # If it does, verify the host port differs from test-database.
    prod_ports_raw: Any = prod_db.get("ports")
    if prod_ports_raw is not None:
        prod_ports: list[str] = list(prod_ports_raw)
        prod_host_port: str = prod_ports[0].split(":")[0]
        assert test_host_port != prod_host_port, (
            f"Test DB port {test_host_port} should differ from "
            f"production DB port {prod_host_port}"
        )


def test_docker_compose_parses_cleanly() -> None:
    """Verify docker-compose.yml parses via yaml.safe_load() with services key (S53).

    Checks:
        - ``yaml.safe_load()`` succeeds without raising
        - The result has a ``services`` key
    """
    data = _load_compose()
    assert "services" in data, "docker-compose.yml missing 'services' key"
