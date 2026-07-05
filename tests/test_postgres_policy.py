"""Policy enforcement gatekeeper for PostgreSQL integration tests.

Block 6 governance: ensures postgres test policy is maintained over time.
Scenarios: PP1-PP5.

IMPORTANT: Banned patterns constructed via string concatenation to avoid
self-triggering the root-mode checker.  This file is listed in EXCLUDE_FILES
for belt-and-suspenders safety.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

_REPO_ROOT: Path = Path(__file__).resolve().parent.parent
_INTEGRATION_DB_DIR: Path = _REPO_ROOT / "tests" / "integration" / "db"
_RUNNER_SCRIPT: Path = _REPO_ROOT / "scripts" / "run-postgres-tests.sh"
_MAKEFILE: Path = _REPO_ROOT / "Makefile"

# Type alias for sync and async function-definition AST nodes.
_FunctionDefNode = ast.FunctionDef | ast.AsyncFunctionDef

# Banned mock-pool patterns for PP2.
#
# Constructed via string concatenation to avoid self-triggering the
# root-mode hardcode checker.  This file is also listed in EXCLUDE_FILES
# of ``scripts/check-test-hardcodes.sh`` for belt-and-suspenders safety.
_BANNED_MOCK_PATTERNS: list[str] = [
    "Mag" + "icMock",
    "As" + "ynMock",
    'patch("asyncpg',
    'patch("src.db',
    "Mock()",
]


def _line_index(lines: list[str], pattern: str) -> int | None:
    """Return the 0-based index of the first line containing ``pattern``.

    Args:
        lines: Script source split into lines.
        pattern: Substring to search for.

    Returns:
        Index of the first matching line, or ``None`` if not found.
    """
    return next((i for i, line in enumerate(lines) if pattern in line), None)


def _function_uses_real_pool(node: _FunctionDefNode) -> bool:
    """Check if function body references ``pg_pool.acquire()`` or ``db_manager``.

    Unparses the AST node to source text and searches for substrings
    indicating direct usage of the real database pool or the
    ``DatabaseManager`` facade.

    Args:
        node: A sync or async function-definition AST node.

    Returns:
        True if the function source references ``pg_pool.acquire()``
        or ``db_manager``.
    """
    source: str = ast.unparse(node)
    return "pg_pool.acquire()" in source or "db_manager" in source


def _decorator_to_string(node: ast.expr) -> str:
    """Convert a decorator AST node to its string representation.

    Args:
        node: Decorator expression node from a function's
            ``decorator_list``.

    Returns:
        Source-text representation of the decorator (e.g.
        ``"pytest.mark.postgres"``).
    """
    return ast.unparse(node)


def _has_postgres_marker(node: _FunctionDefNode) -> bool:
    """Check if function has ``@pytest.mark.postgres`` decorator.

    Args:
        node: A sync or async function-definition AST node.

    Returns:
        True if any decorator in ``node.decorator_list`` contains
        ``pytest.mark.postgres``.
    """
    for deco in node.decorator_list:
        if "pytest.mark.postgres" in _decorator_to_string(deco):
            return True
    return False


# ── PP1: All postgres integration tests must have @pytest.mark.postgres ────


@pytest.mark.postgres
def test_all_postgres_tests_have_marker() -> None:
    """Verify every test using the real pool carries the postgres marker.

    AST-scans all ``test_*.py`` files in ``tests/integration/db/`` and
    finds function definitions whose body references ``pg_pool.acquire()``
    or ``db_manager``.  Each such function must be decorated with
    ``@pytest.mark.postgres``.

    Scenarios:
        (1) ``pg_pool`` usage without marker is detected.
        (2) ``db_manager`` usage without marker is detected.
        (3) Correctly marked functions pass.
    """
    violations: list[str] = []

    if _INTEGRATION_DB_DIR.is_dir():
        for test_file in sorted(_INTEGRATION_DB_DIR.glob("test_*.py")):
            source: str = test_file.read_text(encoding="utf-8")
            tree: ast.Module = ast.parse(source, filename=str(test_file))
            for node in ast.walk(tree):
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                if not node.name.startswith("test_"):
                    continue
                if _function_uses_real_pool(node) and not _has_postgres_marker(node):
                    rel: str = test_file.relative_to(_REPO_ROOT).as_posix()
                    violations.append(f"{rel}::{node.name}")

    assert (
        not violations
    ), "Functions using the real pool must have @pytest.mark.postgres:\n" + "\n".join(
        f"  {v}" for v in violations
    )


# ── PP2: No mock pools in postgres integration tests ───────────────────────


@pytest.mark.postgres
def test_no_mock_pool_in_postgres_tests() -> None:
    """Verify no mock-pool patterns appear in postgres integration tests.

    String-scans all ``test_*.py`` files in ``tests/integration/db/`` for
    banned mocking patterns.  Postgres tests must use the real pool, not
    mocked pools.

    Scenarios:
        (1) ``MagicMock`` usage is detected.
        (2) ``asyncpg`` pool patch is detected.
        (3) Clean files pass.
    """
    violations: list[str] = []

    if _INTEGRATION_DB_DIR.is_dir():
        for test_file in sorted(_INTEGRATION_DB_DIR.glob("test_*.py")):
            lines: list[str] = test_file.read_text(encoding="utf-8").splitlines()
            rel: str = test_file.relative_to(_REPO_ROOT).as_posix()
            for line_num, line in enumerate(lines, start=1):
                for pattern in _BANNED_MOCK_PATTERNS:
                    if pattern in line:
                        violations.append(f"{rel}:{line_num}: {line.strip()}")

    assert not violations, (
        "Mock-pool patterns must not appear in postgres integration tests:\n"
        + "\n".join(f"  {v}" for v in violations)
    )


# ── PP3: run-postgres-tests.sh always starts fresh ────────────────────────


@pytest.mark.postgres
def test_run_postgres_script_always_starts_fresh() -> None:
    """Verify the runner script tears down before and after tests.

    Reads ``scripts/run-postgres-tests.sh`` and asserts:

    - At least two ``down -v`` calls (pre-teardown + post-teardown).
    - Lifecycle ordering: pre-down < up --wait < first run_group < post-down.

    Scenarios:
        (1) Both pre/post teardown use ``down -v``.
        (2) Lifecycle ordering is correct.
    """
    script: str = _RUNNER_SCRIPT.read_text(encoding="utf-8")
    lines: list[str] = script.splitlines()

    down_count: int = sum(1 for line in lines if "down" in line and "-v" in line)
    assert (
        down_count >= 2
    ), f"Expected >= 2 'down -v' calls (pre+post teardown), got {down_count}"

    pre_down: int | None = _line_index(lines, "down -v")
    up_idx: int | None = _line_index(lines, "up -d --wait test-database")
    first_run_group: int | None = _line_index(lines, 'run_group "schema"')
    post_down: int = max(i for i, line in enumerate(lines) if "down -v" in line)

    assert pre_down is not None, "Pre-teardown 'down -v' not found"
    assert up_idx is not None, "'up -d --wait test-database' not found"
    assert first_run_group is not None, "run_group 'schema' call not found"
    assert (
        pre_down < up_idx < first_run_group < post_down
    ), "Lifecycle order must be: pre-down < up --wait < run_group < post-down"


# ── PP4: run-postgres-tests.sh uses v2 compose syntax ─────────────────────


@pytest.mark.postgres
def test_run_postgres_script_uses_v2_compose() -> None:
    """Verify the runner script uses v2 compose syntax and ``--wait``.

    Reads ``scripts/run-postgres-tests.sh`` and asserts:

    - Uses ``podman compose`` or ``docker compose`` (v2, space-separated).
    - Does not use ``docker-compose`` (v1, hyphenated).
    - Uses ``--wait`` for container readiness.
    - Does not use ``sleep`` for readiness.

    Scenarios:
        (1) v2 compose with podman/docker.
        (2) ``--wait`` instead of ``sleep``.
    """
    script: str = _RUNNER_SCRIPT.read_text(encoding="utf-8")

    assert (
        "podman compose" in script or "docker compose" in script
    ), "Missing v2 compose syntax (space-separated)"
    assert (
        "docker-compose" not in script
    ), "Must not use v1 'docker-compose' (hyphenated) syntax"
    assert "--wait" in script, "Missing '--wait' readiness flag"
    assert (
        "sleep" not in script
    ), "'sleep' must not be used for readiness; use '--wait' instead"


# ── PP5: Makefile test-postgres delegates to the script ───────────────────


@pytest.mark.postgres
def test_makefile_postgres_target_delegates_to_script() -> None:
    """Verify the Makefile ``test-postgres`` target delegates to the script.

    Reads the ``Makefile`` and asserts:

    - The ``test-postgres`` target runs ``bash scripts/run-postgres-tests.sh``.
    - The Makefile does not run ``pytest --run-postgres`` inline.

    Scenarios:
        (1) Makefile delegates to the lifecycle script.
    """
    makefile: str = _MAKEFILE.read_text(encoding="utf-8")

    assert (
        "bash scripts/run-postgres-tests.sh" in makefile
    ), "test-postgres target must run 'bash scripts/run-postgres-tests.sh'"
    assert (
        "poetry run pytest --run-postgres" not in makefile
    ), "test-postgres must not run 'pytest --run-postgres' inline"
