# tests/integration/test_docker_compose.py
"""Integration tests for docker-compose.yml and Dockerfile configuration.

Test IDs:
  IT-D01 – gateway command is uvicorn-based with host/port/workers
  IT-D02 – worker command is ["python", "main.py", "keeper"]
  IT-D03 – gateway environment contains GATEWAY_WORKERS=4
  IT-D04 – gateway environment contains PROMETHEUS_MULTIPROC_DIR
  IT-D05 – gateway volumes contain prometheus_data mount
  IT-D06 – Keeper does NOT expose port 9090 externally (internal only)
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
        return cast(dict[str, Any], yaml.load(f))  # pyright: ignore[reportUnknownMemberType]


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
        "0.0.0.0",
        "--port",
        "55300",
        "--workers",
        "4",
    ]
    assert gateway_command == expected, (
        f"gateway command mismatch: expected {expected}, got {gateway_command}"
    )


# ---------------------------------------------------------------------------
# IT-D02: worker command
# ---------------------------------------------------------------------------


def test_it_d02_worker_command() -> None:
    """IT-D02: worker command == ["python", "main.py", "keeper"] (unchanged)."""
    data = _load_compose()
    worker_command: list[str] = list(data["services"]["worker"]["command"])
    expected = ["python", "main.py", "keeper"]
    assert worker_command == expected, (
        f"worker command mismatch: expected {expected}, got {worker_command}"
    )


# ---------------------------------------------------------------------------
# IT-D03: gateway environment GATEWAY_WORKERS
# ---------------------------------------------------------------------------


def test_it_d03_gateway_env_gateway_workers() -> None:
    """IT-D03: gateway environment contains GATEWAY_WORKERS=4."""
    data = _load_compose()
    env: list[str] = list(data["services"]["gateway"]["environment"])
    assert "GATEWAY_WORKERS=4" in env, (
        f"GATEWAY_WORKERS=4 not found in gateway environment: {env}"
    )


# ---------------------------------------------------------------------------
# IT-D04: gateway environment PROMETHEUS_MULTIPROC_DIR
# ---------------------------------------------------------------------------


def test_it_d04_gateway_env_prometheus_multiproc_dir() -> None:
    """IT-D04: gateway environment contains
    PROMETHEUS_MULTIPROC_DIR=/tmp/prometheus_multiproc.
    """
    data = _load_compose()
    env: list[str] = list(data["services"]["gateway"]["environment"])
    assert "PROMETHEUS_MULTIPROC_DIR=/tmp/prometheus_multiproc" in env, (
        f"PROMETHEUS_MULTIPROC_DIR=/tmp/prometheus_multiproc not found "
        f"in gateway environment: {env}"
    )


# ---------------------------------------------------------------------------
# IT-D05: gateway volumes prometheus_data mount
# ---------------------------------------------------------------------------


def test_it_d05_gateway_volumes_prometheus_data() -> None:
    """IT-D05: gateway volumes contain prometheus_data:/tmp/prometheus_multiproc."""
    data = _load_compose()
    volumes: list[str] = list(data["services"]["gateway"]["volumes"])
    assert "prometheus_data:/tmp/prometheus_multiproc" in volumes, (
        f"prometheus_data:/tmp/prometheus_multiproc not found "
        f"in gateway volumes: {volumes}"
    )


# ---------------------------------------------------------------------------
# IT-D06: Keeper does NOT expose port 9090 externally
# ---------------------------------------------------------------------------


def test_it_d06_keeper_no_external_port_9090() -> None:
    """IT-D06: Keeper (worker service) does NOT expose port 9090 externally.

    The worker service should either have no 'ports' section at all,
    or no mapping that exposes 9090 to the host.
    """
    data = _load_compose()
    worker_service: dict[str, Any] = data["services"]["worker"]
    ports: Any = worker_service.get("ports")
    # No ports section at all → definitely not exposing 9090 externally
    if ports is None:
        return  # passes
    # If ports section exists, verify 9090 is not mapped externally
    for port_mapping in ports:
        port_str = str(port_mapping)
        assert not port_str.startswith("9090"), (
            f"Keeper exposes port 9090 externally: {port_str}"
        )


# ---------------------------------------------------------------------------
# IT-DF01: Dockerfile CMD contains uvicorn main:app
# ---------------------------------------------------------------------------


def test_it_df01_dockerfile_cmd_contains_uvicorn() -> None:
    """IT-DF01: Dockerfile CMD contains 'uvicorn main:app'."""
    content = _read_dockerfile()
    assert "uvicorn" in content, "Dockerfile does not contain 'uvicorn'"
    assert "main:app" in content, "Dockerfile does not contain 'main:app'"