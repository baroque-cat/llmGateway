"""Tests for test-infrastructure polish: file relocation, Makefile targets, scaffolds.

Verifies that the ``test_keeper_metrics.py`` file was relocated from
``tests/unit/services/`` to ``tests/unit/metrics/``, that the shared
``mock_run_keeper_dependencies`` fixture is defined in
``tests/unit/conftest.py``, that the Makefile exposes standalone
``test-gatekeeper`` and ``test-boundary`` targets, and that the
``tests/integration/db/`` scaffold directory exists with an ``__init__.py``.

Scenarios: relocation, fixture accessibility, gatekeeper target, boundary
target, db scaffold directory, db scaffold init file.
"""

from __future__ import annotations

from pathlib import Path

_REPO_ROOT: Path = Path(__file__).resolve().parent.parent

# Paths for the keeper-metrics relocation scenario.
_METRICS_KEEPER_METRICS: Path = (
    _REPO_ROOT / "tests" / "unit" / "metrics" / "test_keeper_metrics.py"
)
_SERVICES_KEEPER_METRICS: Path = (
    _REPO_ROOT / "tests" / "unit" / "services" / "test_keeper_metrics.py"
)
_UNIT_CONFTEST: Path = _REPO_ROOT / "tests" / "unit" / "conftest.py"

# Paths for the Makefile target scenarios.
_MAKEFILE: Path = _REPO_ROOT / "Makefile"

# Paths for the integration db scaffold scenario.
_INTEGRATION_DB_DIR: Path = _REPO_ROOT / "tests" / "integration" / "db"
_INTEGRATION_DB_INIT: Path = _INTEGRATION_DB_DIR / "__init__.py"

# Expected Makefile target command fragments.
_GATEKEEPER_COMMAND: str = (
    "poetry run pytest tests/ --ignore=tests/unit "
    "--ignore=tests/integration --ignore=tests/security "
    "--ignore=tests/e2e --ignore=tests/stress --ignore=tests/batching "
    '-q --timeout=30 -m "not slow and not postgres"'
)
_BOUNDARY_COMMAND: str = (
    "poetry run pytest tests/test_boundary_compliance.py -q --timeout=30"
)


class TestTestInfraPolish:
    """Tests for test-infrastructure polish requirements."""

    def test_keeper_metrics_file_is_in_metrics_dir(self) -> None:
        """Relocation: ``test_keeper_metrics.py`` exists in the metrics directory.

        Verifies that ``tests/unit/metrics/test_keeper_metrics.py`` exists as
        a regular file after the relocation.
        """
        assert _METRICS_KEEPER_METRICS.is_file(), (
            f"Expected {_METRICS_KEEPER_METRICS} to exist as a file"
        )

    def test_keeper_metrics_file_not_in_services_dir(self) -> None:
        """Relocation: ``test_keeper_metrics.py`` is gone from the services directory.

        Verifies that ``tests/unit/services/test_keeper_metrics.py`` does NOT
        exist, confirming the file was moved rather than copied.
        """
        assert not _SERVICES_KEEPER_METRICS.exists(), (
            f"Expected {_SERVICES_KEEPER_METRICS} to NOT exist (file was moved)"
        )

    def test_mock_run_keeper_fixture_in_unit_conftest(self) -> None:
        """Fixture accessibility: ``mock_run_keeper_dependencies`` in unit conftest.

        Reads ``tests/unit/conftest.py`` and verifies that the shared
        ``mock_run_keeper_dependencies`` fixture is defined there so both the
        ``tests/unit/services/`` and ``tests/unit/metrics/`` subtrees have
        access to it.
        """
        conftest = _UNIT_CONFTEST.read_text()
        assert "def mock_run_keeper_dependencies" in conftest, (
            "mock_run_keeper_dependencies fixture not defined in "
            f"{_UNIT_CONFTEST}"
        )

    def test_makefile_has_test_gatekeeper_target(self) -> None:
        """Gatekeeper target: ``test-gatekeeper`` runs root-level tests only.

        Reads the ``Makefile`` and verifies that a ``test-gatekeeper`` target
        exists and runs the expected pytest invocation collecting root-level
        tests while ignoring all subdirectories.
        """
        makefile = _MAKEFILE.read_text()
        assert "test-gatekeeper:" in makefile, (
            "test-gatekeeper target not found in Makefile"
        )
        assert _GATEKEEPER_COMMAND in makefile, (
            f"test-gatekeeper target does not run expected command: "
            f"{_GATEKEEPER_COMMAND}"
        )

    def test_makefile_has_test_boundary_target(self) -> None:
        """Boundary target: ``test-boundary`` runs a single-file fast check.

        Reads the ``Makefile`` and verifies that a ``test-boundary`` target
        exists and runs the expected pytest invocation against
        ``tests/test_boundary_compliance.py``.
        """
        makefile = _MAKEFILE.read_text()
        assert "test-boundary:" in makefile, (
            "test-boundary target not found in Makefile"
        )
        assert _BOUNDARY_COMMAND in makefile, (
            f"test-boundary target does not run expected command: "
            f"{_BOUNDARY_COMMAND}"
        )

    def test_integration_db_dir_exists(self) -> None:
        """DB scaffold: ``tests/integration/db/`` directory exists.

        Verifies that the ``tests/integration/db/`` directory exists as a
        scaffold for future PostgreSQL integration tests.
        """
        assert _INTEGRATION_DB_DIR.is_dir(), (
            f"Expected directory {_INTEGRATION_DB_DIR} to exist"
        )

    def test_integration_db_has_init_file(self) -> None:
        """DB scaffold: ``tests/integration/db/__init__.py`` exists.

        Verifies that the ``tests/integration/db/`` directory contains an
        ``__init__.py`` file (may be empty) marking it as a Python package.
        """
        assert _INTEGRATION_DB_INIT.is_file(), (
            f"Expected {_INTEGRATION_DB_INIT} to exist as a file"
        )
