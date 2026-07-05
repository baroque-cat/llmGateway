"""Regression gatekeeper tests for ``scripts/check-test-hardcodes.sh``.

Test Group: hardcode-checker-regression

Verifies the gatekeeper script produces no false positives on the current
clean codebase across all supported modes, validates determinism across
repeated runs, confirms the no-args default equals the ``all`` mode, and
checks that the EXCLUDE_FILES array covers all gatekeeper test files.

Scenarios: S17, S18, S19, S20, S21, S22, S23, S24.
"""

# pyright: reportPrivateUsage=false

from __future__ import annotations

import subprocess
from collections.abc import Callable

import pytest

from tests.conftest import _CHECKER_SCRIPT, _REPO_ROOT, CheckerResult

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run_script(mode: str) -> subprocess.CompletedProcess[str]:
    """Run the checker script with the given mode.

    Args:
        mode: One of ``canonical``, ``boundary``, ``root``, ``all``.

    Returns:
        The completed subprocess result with stdout/stderr captured.
    """
    return subprocess.run(  # noqa: S603
        ["bash", str(_CHECKER_SCRIPT), mode],  # noqa: S603
        capture_output=True,
        text=True,
        cwd=str(_REPO_ROOT),
        timeout=60,
    )


def _normalize_output(output: str) -> str:
    """Normalize checker output for deterministic comparison.

    Strips leading/trailing whitespace from each line, drops empty lines,
    and sorts the remaining lines.  The checker output is deterministic
    (no timestamps), but normalizing ensures robust comparison.

    Args:
        output: Raw stdout or stderr from the checker script.

    Returns:
        Sorted, stripped, newline-joined output string.
    """
    return "\n".join(
        sorted(line.strip() for line in output.splitlines() if line.strip())
    )


def _cleanup_stale_synth_files() -> None:
    """Remove stale synthetic test files from previous sessions.

    Other gatekeeper tests (``test_hardcode_checker_core.py``,
    ``test_hardcode_checker_production_urls.py``) create temporary
    ``_gate_synth_*.py`` files with ``delete=False`` to test the checker's
    violation detection.  If a previous session crashed or left files
    behind, they contaminate the checker's directory scan.  The
    session-scoped ``_cleanup_stale_temp_files`` fixture in
    ``conftest.py`` only removes ``tmp*.py`` files, not ``_gate_synth_*``
    files, so this helper fills that gap.
    """
    tests_dir = _REPO_ROOT / "tests"
    if not tests_dir.is_dir():
        return
    for pattern in ("_gate_synth_*.py", "tmp*.py"):
        for stale in tests_dir.rglob(pattern):
            if stale.is_file():
                stale.unlink(missing_ok=True)


@pytest.fixture(scope="session", autouse=True)
def _session_synth_cleanup() -> None:  # pyright: ignore[reportUnusedFunction]
    """Remove stale ``_gate_synth_*.py`` files at session start.

    Runs before the session-scoped ``_cached_checker_results`` fixture
    (autouse fixtures execute before non-autouse fixtures of the same
    scope) to ensure the cache captures a clean codebase.
    """
    _cleanup_stale_synth_files()


# Gatekeeper test files that must appear in the script's EXCLUDE_FILES array
# so the checker does not flag its own test infrastructure.
_GATEKEEPER_TEST_FILES: list[str] = [
    "test_canonical_config.py",
    "test_canonical_fixtures.py",
    "test_constants.py",
    "test_hardcode_checker_modes.py",
    "test_hardcode_checker_patterns.py",
    "test_conftest_checker_cache.py",
    "test_project_structure.py",
    "test_makefile_groups.py",
    "test_canonical_integrity.py",
    "test_secret_isolation.py",
    "test_env_example.py",
    "test_documentation_sync.py",
    "test_testing_docs.py",
    "test_hardcode_checker_core.py",
    "test_hardcode_checker_production_urls.py",
    "test_boundary_compliance.py",
    "test_hardcode_checker_regression.py",
    "test_docker_test_db.py",
    "test_security.py",
    "test_ci_pipeline.py",
    "test_layer_import_scan.py",
    "test_pre_commit_config.py",
    "test_metrics_fixture_dedup.py",
    "test_postgres_runner.py",
    "test_test_infra_polish.py",
    "test_postgres_policy.py",
    "test_pyright_tiered_config.py",
    "test_pyright_ci_gate.py",
]


# ---------------------------------------------------------------------------
# S17-S20: Cache fixture passes on clean codebase
# ---------------------------------------------------------------------------


def test_all_mode_passes_on_clean_codebase(
    checker_result: Callable[..., CheckerResult],
) -> None:
    """S17: ``all`` mode exits 0 on the current clean codebase.

    Uses the ``checker_result`` cache fixture which composes the
    canonical, boundary, and root results into a single ``all`` result.
    """
    result = checker_result("all")
    assert result.returncode == 0


def test_canonical_mode_passes(
    checker_result: Callable[..., CheckerResult],
) -> None:
    """S18: ``canonical`` mode exits 0 — ``tests/unit/`` is clean."""
    result = checker_result("canonical")
    assert result.returncode == 0


def test_boundary_mode_passes(
    checker_result: Callable[..., CheckerResult],
) -> None:
    """S19: ``boundary`` mode exits 0 — boundary directories are clean."""
    result = checker_result("boundary")
    assert result.returncode == 0


def test_root_mode_passes(
    checker_result: Callable[..., CheckerResult],
) -> None:
    """S20: ``root`` mode exits 0 — root-level test files are clean."""
    result = checker_result("root")
    assert result.returncode == 0


# ---------------------------------------------------------------------------
# S21: Output consistency across repeated runs
# ---------------------------------------------------------------------------


def test_output_consistent_across_runs() -> None:
    """S21: Running the checker twice produces identical normalized output.

    Invokes the script directly via ``subprocess.run`` (not the cache
    fixture) twice in ``all`` mode, normalizes both outputs with
    ``_normalize_output()``, and asserts they are identical.
    """
    _cleanup_stale_synth_files()
    run1 = _run_script("all")
    _cleanup_stale_synth_files()
    run2 = _run_script("all")

    assert run1.returncode == run2.returncode
    assert _normalize_output(run1.stdout) == _normalize_output(run2.stdout)
    assert _normalize_output(run1.stderr) == _normalize_output(run2.stderr)


# ---------------------------------------------------------------------------
# S22: No-args invocation equals ``all`` mode
# ---------------------------------------------------------------------------


def test_no_args_equals_all_mode() -> None:
    """S22: Running with no arguments produces the same output as ``all`` mode.

    Runs the script with no mode argument (defaults to ``all``) and with
    the explicit ``all`` argument, then asserts both return codes and
    normalized outputs match.
    """
    _cleanup_stale_synth_files()
    result_no_args = subprocess.run(  # noqa: S603
        ["bash", str(_CHECKER_SCRIPT)],  # noqa: S603
        capture_output=True,
        text=True,
        cwd=str(_REPO_ROOT),
        timeout=60,
    )
    _cleanup_stale_synth_files()
    result_all = subprocess.run(  # noqa: S603
        ["bash", str(_CHECKER_SCRIPT), "all"],  # noqa: S603
        capture_output=True,
        text=True,
        cwd=str(_REPO_ROOT),
        timeout=60,
    )

    assert result_no_args.returncode == result_all.returncode
    assert _normalize_output(result_no_args.stdout) == _normalize_output(
        result_all.stdout
    )
    assert _normalize_output(result_no_args.stderr) == _normalize_output(
        result_all.stderr
    )


# ---------------------------------------------------------------------------
# S23: Success summary line present
# ---------------------------------------------------------------------------


def test_summary_line_present_on_success(
    checker_result: Callable[..., CheckerResult],
) -> None:
    """S23: The success summary line is present in ``all`` mode output.

    Asserts that ``checker_result("all").stdout`` contains the canonical
    success message ``"All test hardcode checks passed"``.
    """
    result = checker_result("all")
    assert "All test hardcode checks passed" in result.stdout


# ---------------------------------------------------------------------------
# S24: EXCLUDE_FILES covers all gatekeeper test files
# ---------------------------------------------------------------------------


def test_exclude_files_covers_all_gatekeeper_tests() -> None:
    """S24: The EXCLUDE_FILES array lists all known gatekeeper test files.

    Parses the checker script source text line by line, extracts the
    EXCLUDE_FILES array entries (double-quoted filenames), and asserts
    every known gatekeeper test file is present so the checker does not
    flag its own test infrastructure.
    """
    script_text = _CHECKER_SCRIPT.read_text()
    excluded_entries: list[str] = []
    in_exclude = False
    for raw_line in script_text.splitlines():
        stripped = raw_line.strip()
        if stripped == "EXCLUDE_FILES=(":
            in_exclude = True
            continue
        if in_exclude:
            if stripped == ")":
                break
            if stripped.startswith('"') and stripped.endswith('"'):
                excluded_entries.append(stripped.strip('"'))

    for gatekeeper_file in _GATEKEEPER_TEST_FILES:
        assert gatekeeper_file in excluded_entries, (
            f"Gatekeeper test file {gatekeeper_file!r} not found in "
            f"EXCLUDE_FILES array of {_CHECKER_SCRIPT.name}"
        )
