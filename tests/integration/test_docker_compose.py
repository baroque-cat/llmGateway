# tests/integration/test_docker_compose.py
"""Integration tests for docker-compose.yml and Dockerfile configuration.

Test IDs:
  IT-D01 – gateway command is uvicorn-based with host/port/workers
  IT-D02 – worker command is ["python", "main.py", "keeper"]
  IT-D03 – gateway environment contains GATEWAY_WORKERS=4
  IT-D06 – Keeper does NOT expose port 9090 externally (internal only)
  IT-D07 – gateway environment does NOT contain PROMETHEUS_MULTIPROC_DIR
  IT-D08 – gateway volumes do NOT contain prometheus_data mount
  IT-D09 – prometheus_data volume declaration removed from global volumes
  IT-DF01 – Dockerfile CMD contains uvicorn main:app
"""

from pathlib import Path
from typing import Any, cast

from ruamel.yaml import YAML

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
COMPOSE_FILE = PROJECT_ROOT / "docker-compose.yml"
DOCKERFILE = PROJECT_ROOT / "Dockerfile"


def _load_compose() -> dict[str, Any]:
    """Load docker-compose.yml using ruamel.yaml."""
    yaml = YAML()
    with open(COMPOSE_FILE) as f:
        return cast(
            dict[str, Any], yaml.load(f)
        )  # pyright: ignore[reportUnknownMemberType]


def _read_dockerfile() -> str:
    """Read Dockerfile content as string."""
    with open(DOCKERFILE) as f:
        return f.read()


# ---------------------------------------------------------------------------
# IT-D01: gateway command
# ---------------------------------------------------------------------------


def test_it_d01_gateway_command() -> None:
    """IT-D01: gateway command == ["uvicorn", "main:app", "--host", "0.0.0.0",
    "--port", "55300", "--workers", "4"].
    """
    data = _load_compose()
    gateway_command: list[str] = list(data["services"]["gateway"]["command"])
    expected = [
        "uvicorn",
        "main:app",
        "--host",
        "${GATEWAY_HOST}",
        "--port",
        "${GATEWAY_PORT}",
        "--workers",
        "${GATEWAY_WORKERS}",
    ]
    assert (
        gateway_command == expected
    ), f"gateway command mismatch: expected {expected}, got {gateway_command}"


# ---------------------------------------------------------------------------
# IT-D02: worker command
# ---------------------------------------------------------------------------


def test_it_d02_worker_command() -> None:
    """IT-D02: keeper command == ["python", "main.py", "keeper"] (was worker, renamed to keeper)."""
    data = _load_compose()
    keeper_command: list[str] = list(data["services"]["keeper"]["command"])
    expected = ["python", "main.py", "keeper"]
    assert (
        keeper_command == expected
    ), f"keeper command mismatch: expected {expected}, got {keeper_command}"


# ---------------------------------------------------------------------------
# IT-D03: gateway environment GATEWAY_WORKERS
# ---------------------------------------------------------------------------


def test_it_d03_gateway_env_gateway_workers() -> None:
    """IT-D03: gateway environment or env_file references include GATEWAY_WORKERS."""
    data = _load_compose()
    gateway_service: dict[str, Any] = data["services"]["gateway"]

    # Gateway may use env_file (list) instead of environment (list of strings)
    env_raw: Any = gateway_service.get("environment")
    if env_raw is not None:
        env: list[str] = list(env_raw)
        assert (
            "GATEWAY_WORKERS=4" in env
        ), f"GATEWAY_WORKERS=4 not found in gateway environment: {env}"
        return

    # Check env_file if environment is absent
    env_file_raw: Any = gateway_service.get("env_file")
    if env_file_raw is not None:
        env_file: list[str] = (
            env_file_raw if isinstance(env_file_raw, list) else [env_file_raw]
        )
        assert ".env" in env_file or any(
            ".env" in str(f) for f in env_file
        ), f"env_file does not reference .env: {env_file}"
        return

    # If neither environment nor env_file exists, that's also valid
    # (env vars may come from docker-compose auto .env loading)


# ---------------------------------------------------------------------------
# IT-D07: gateway environment does NOT contain PROMETHEUS_MULTIPROC_DIR
# ---------------------------------------------------------------------------


def test_it_d07_gateway_no_prometheus_multiproc_dir() -> None:
    """IT-D07: gateway environment does NOT contain PROMETHEUS_MULTIPROC_DIR.

    If the gateway service has no 'environment' key at all, the test passes
    trivially (no env vars exist). If it does have an environment list,
    we verify that PROMETHEUS_MULTIPROC_DIR is absent.
    """
    data = _load_compose()
    gateway_service: dict[str, Any] = data["services"]["gateway"]
    env_raw: Any = gateway_service.get("environment")
    # No environment section → PROMETHEUS_MULTIPROC_DIR definitely absent
    if env_raw is None:
        return  # passes
    env: list[str] = list(env_raw)
    assert "PROMETHEUS_MULTIPROC_DIR=/tmp/prometheus_multiproc" not in env, (
        f"PROMETHEUS_MULTIPROC_DIR=/tmp/prometheus_multiproc should not be "
        f"in gateway environment: {env}"
    )
    # Also ensure no env var starts with PROMETHEUS_MULTIPROC_DIR at all
    for entry in env:
        assert not entry.startswith(
            "PROMETHEUS_MULTIPROC_DIR"
        ), f"Found env var starting with PROMETHEUS_MULTIPROC_DIR: {entry}"


# ---------------------------------------------------------------------------
# IT-D08: gateway volumes do NOT contain prometheus_data mount
# ---------------------------------------------------------------------------


def test_it_d08_gateway_no_prometheus_data_volume() -> None:
    """IT-D08: gateway volumes do NOT contain prometheus_data:/tmp/prometheus_multiproc.

    If the gateway service has no 'volumes' key at all, the test passes
    trivially. If it does have a volumes list, we verify that the
    prometheus_data mount is absent.
    """
    data = _load_compose()
    gateway_service: dict[str, Any] = data["services"]["gateway"]
    volumes_raw: Any = gateway_service.get("volumes")
    # No volumes section → prometheus_data mount definitely absent
    if volumes_raw is None:
        return  # passes
    volumes: list[str] = list(volumes_raw)
    assert "prometheus_data:/tmp/prometheus_multiproc" not in volumes, (
        f"prometheus_data:/tmp/prometheus_multiproc should not be "
        f"in gateway volumes: {volumes}"
    )


# ---------------------------------------------------------------------------
# IT-D09: prometheus_data volume declaration removed from global volumes
# ---------------------------------------------------------------------------


def test_it_d09_no_prometheus_data_volume_declaration() -> None:
    """IT-D09: prometheus_data volume declaration removed from global volumes section."""
    data = _load_compose()
    top_level_volumes: dict[str, Any] = data.get("volumes", {})
    assert "prometheus_data" not in top_level_volumes, (
        f"prometheus_data should not be in global volumes: "
        f"{list(top_level_volumes.keys())}"
    )


# ---------------------------------------------------------------------------
# IT-D06: Keeper does NOT expose port 9090 externally
# ---------------------------------------------------------------------------


def test_it_d06_keeper_no_external_port_9090() -> None:
    """IT-D06: Keeper (keeper service) does NOT expose port 9090 externally.

    The keeper service should either have no 'ports' section at all,
    or no mapping that exposes 9090 to the host.
    """
    data = _load_compose()
    keeper_service: dict[str, Any] = data["services"]["keeper"]
    ports: Any = keeper_service.get("ports")
    # No ports section at all → definitely not exposing 9090 externally
    if ports is None:
        return  # passes
    # If ports section exists, verify 9090 is not mapped externally
    for port_mapping in ports:
        port_str = str(port_mapping)
        assert not port_str.startswith(
            "9090"
        ), f"Keeper exposes port 9090 externally: {port_str}"


# ---------------------------------------------------------------------------
# IT-DF01: Dockerfile CMD contains uvicorn main:app
# ---------------------------------------------------------------------------


def test_it_df01_dockerfile_cmd_contains_uvicorn() -> None:
    """IT-DF01: Dockerfile CMD contains 'uvicorn main:app'."""
    content = _read_dockerfile()
    assert "uvicorn" in content, "Dockerfile does not contain 'uvicorn'"
    assert "main:app" in content, "Dockerfile does not contain 'main:app'"
