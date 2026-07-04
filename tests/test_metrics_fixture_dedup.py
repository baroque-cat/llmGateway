#!/usr/bin/env python3

"""Gatekeeper tests for metrics fixture de-duplication.

Verifies that the ``_isolate_metrics_collector`` autouse fixture is
defined only in the appropriate conftest files and not duplicated
in individual test modules.  Uses structural source-scanning (reading
files as text) rather than runtime checks.
"""

from pathlib import Path

_REPO_ROOT: Path = Path(__file__).resolve().parent.parent

# Fixture names that must NOT be defined in individual test files.
_DUPLICATE_FIXTURE_NAMES: list[str] = [
    "_isolate_metrics_collector",
    "_clean_env_and_singleton",
    "_isolate_collector_for_memory_backend",
    "_isolate_collector",
]


def test_no_duplicate_isolation_fixtures_in_metrics_unit_tests() -> None:
    """No test file in tests/unit/metrics/ defines its own isolation fixture.

    Scans all ``.py`` files in ``tests/unit/metrics/`` (excluding
    ``conftest.py`` and ``__pycache__``) and verifies none define
    their own ``_isolate_metrics_collector``,
    ``_clean_env_and_singleton``,
    ``_isolate_collector_for_memory_backend``, or
    ``_isolate_collector`` autouse fixture.
    """
    metrics_dir = _REPO_ROOT / "tests" / "unit" / "metrics"
    for py_file in metrics_dir.rglob("*.py"):
        if py_file.name == "conftest.py":
            continue
        if "__pycache__" in py_file.parts:
            continue
        content = py_file.read_text()
        for name in _DUPLICATE_FIXTURE_NAMES:
            assert (
                f"def {name}" not in content
            ), f"{py_file} defines duplicate fixture '{name}'"


def test_unit_conftest_re_exports_isolation_fixture() -> None:
    """tests/unit/conftest.py re-exports _isolate_metrics_collector.

    Verifies that the unit-level conftest imports
    ``_isolate_metrics_collector`` from
    ``tests.unit.metrics.conftest`` so that tests in other
    subdirectories also receive metrics isolation.
    """
    conftest_path = _REPO_ROOT / "tests" / "unit" / "conftest.py"
    content = conftest_path.read_text()
    assert "_isolate_metrics_collector" in content
    assert "tests.unit.metrics.conftest" in content


def test_integration_conftest_provides_isolation_fixture() -> None:
    """tests/integration/conftest.py defines _isolate_metrics_collector as autouse.

    Verifies that the integration conftest defines its own
    ``_isolate_metrics_collector`` as an autouse fixture (contains
    both ``@pytest.fixture(autouse=True)`` and
    ``def _isolate_metrics_collector``).
    """
    conftest_path = _REPO_ROOT / "tests" / "integration" / "conftest.py"
    content = conftest_path.read_text()
    assert "@pytest.fixture(autouse=True)" in content
    assert "def _isolate_metrics_collector" in content


def test_integration_metrics_test_has_no_inline_fixture() -> None:
    """tests/integration/test_keeper_metrics_endpoint.py has no inline fixture.

    Verifies that the integration metrics endpoint test does not
    define its own ``_isolate_collector`` fixture (isolation should
    come from the conftest only).
    """
    test_path = _REPO_ROOT / "tests" / "integration" / "test_keeper_metrics_endpoint.py"
    content = test_path.read_text()
    assert "def _isolate_collector" not in content


def test_prometheus_backend_tests_do_not_use_make_unique_name() -> None:
    """tests/unit/metrics/test_prometheus_backend.py does not use _make_unique_name.

    Verifies that the removed ``_make_unique_name`` helper function
    is not referenced in the prometheus backend tests.
    """
    test_path = _REPO_ROOT / "tests" / "unit" / "metrics" / "test_prometheus_backend.py"
    content = test_path.read_text()
    assert "_make_unique_name" not in content
