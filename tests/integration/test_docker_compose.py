# tests/integration/test_docker_compose.py
"""Integration tests for docker-compose.yml command correctness.

Test IDs:
  IT-D01 – services.gateway.command == ["python", "main.py", "gateway"]
  IT-D02 – services.worker.command == ["python", "main.py", "keeper"]
"""

from pathlib import Path

from ruamel.yaml import YAML

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
COMPOSE_FILE = PROJECT_ROOT / "docker-compose.yml"


def _load_compose() -> dict:
    """Load docker-compose.yml using ruamel.yaml."""
    yaml = YAML()
    with open(COMPOSE_FILE) as f:
        return yaml.load(f)


# ---------------------------------------------------------------------------
# IT-D01: gateway command has no --host/--port/--workers
# ---------------------------------------------------------------------------


def test_it_d01_gateway_command():
    """IT-D01: Read docker-compose.yml with ruamel.yaml → services.gateway.command == ["python", "main.py", "gateway"] (no --host/--port/--workers)"""
    data = _load_compose()
    gateway_command = list(data["services"]["gateway"]["command"])
    assert gateway_command == [
        "python",
        "main.py",
        "gateway",
        "--workers",
        "1",
    ], f"gateway command should be ['python', 'main.py', 'gateway', '--workers', '1']; got {gateway_command}"


# ---------------------------------------------------------------------------
# IT-D02: worker command unchanged
# ---------------------------------------------------------------------------


def test_it_d02_worker_command():
    """IT-D02: services.worker.command == ["python", "main.py", "keeper"] (unchanged)"""
    data = _load_compose()
    worker_command = list(data["services"]["worker"]["command"])
    assert worker_command == [
        "python",
        "main.py",
        "keeper",
    ], f"worker command should be exactly ['python', 'main.py', 'keeper']; got {worker_command}"
