"""Structural test verifying the expected project directory layout (Scenario S17).

Ensures that all required source, test, config, and infrastructure directories
exist at the expected locations.  This is a gatekeeper-level test that prevents
accidental directory renames or deletions.
"""

from pathlib import Path

_REPO_ROOT: Path = Path(__file__).resolve().parent.parent


def test_project_structure_validates_directory_layout() -> None:
    """Verify all required directories and files exist (Scenario S17).

    Checks:
        - ``src/`` with subdirs: config, core, db, metrics, providers, services
        - ``tests/`` with subdirs: unit, integration, security, e2e, stress,
          batching
        - ``tests/unit/`` with subdirs: config, core, db, metrics, providers,
          services
        - ``scripts/`` directory
        - ``config/`` directory with ``example_full_config.yaml``
        - ``.env.example`` at repo root
        - ``tests/conftest.py``, ``tests/_canonical.py``, ``tests/_constants.py``
        - ``tests/AGENTS.md``
    """
    # --- src/ subdirectories ---
    src_subdirs: list[str] = [
        "config",
        "core",
        "db",
        "metrics",
        "providers",
        "services",
    ]
    for subdir in src_subdirs:
        path = _REPO_ROOT / "src" / subdir
        assert path.is_dir(), f"Missing required directory: {path}"

    # --- tests/ subdirectories ---
    tests_subdirs: list[str] = [
        "unit",
        "integration",
        "security",
        "e2e",
        "stress",
        "batching",
    ]
    for subdir in tests_subdirs:
        path = _REPO_ROOT / "tests" / subdir
        assert path.is_dir(), f"Missing required directory: {path}"

    # --- tests/unit/ subdirectories ---
    unit_subdirs: list[str] = [
        "config",
        "core",
        "db",
        "metrics",
        "providers",
        "services",
    ]
    for subdir in unit_subdirs:
        path = _REPO_ROOT / "tests" / "unit" / subdir
        assert path.is_dir(), f"Missing required directory: {path}"

    # --- Top-level directories ---
    assert (_REPO_ROOT / "scripts").is_dir(), "Missing scripts/ directory"
    assert (_REPO_ROOT / "config").is_dir(), "Missing config/ directory"

    # --- Config file ---
    config_file = _REPO_ROOT / "config" / "example_full_config.yaml"
    assert config_file.is_file(), "Missing config/example_full_config.yaml"

    # --- .env.example ---
    env_example = _REPO_ROOT / ".env.example"
    assert env_example.is_file(), "Missing .env.example at repo root"

    # --- Test infrastructure files ---
    infra_files: list[str] = ["conftest.py", "_canonical.py", "_constants.py"]
    for fname in infra_files:
        path = _REPO_ROOT / "tests" / fname
        assert path.is_file(), f"Missing required file: {path}"

    # --- tests/AGENTS.md ---
    agents_md = _REPO_ROOT / "tests" / "AGENTS.md"
    assert agents_md.is_file(), "Missing tests/AGENTS.md"
