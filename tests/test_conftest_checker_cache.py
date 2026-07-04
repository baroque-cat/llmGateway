"""Tier 2 synthetic gatekeeper tests for conftest.py checker cache fixtures.

Tests cover:
- ``_cached_checker_results`` session-scoped fixture (cache population, reuse)
- ``checker_result`` function-scoped accessor (mode access, composition, validation)
- ``_cleanup_stale_temp_files`` session-scoped autouse fixture (stale file removal)
- ``_compute_checker_hash()`` pure function (coverage, determinism, exclusion,
  performance budget)
- Subprocess comparison (cached composition vs. direct invocation)

Scenarios:
  S13: _cached_checker_results runs subprocess.run once per mode (3 calls).
  S14: checker_result provides cached access and composes 'all' mode.
  S15: _cleanup_stale_temp_files removes leftover tmp*.py files.
  S16: _compute_checker_hash reflects file additions/removals.
  S35: Hash changes when the checker script content changes.
  S36: Hash changes when a new .py file appears in a scanned directory.
  S37: Hash excludes __pycache__ entries.
  S37b: Hash excludes __init__.py files.
  S38: _compute_checker_hash is deterministic across calls.
  S39: Hash computation completes within a 1-second budget.
  S40: Cache startup completes within a 10-second budget.
  S41: checker_result("all") matches a direct subprocess invocation.
"""

# pyright: reportPrivateUsage=false

from __future__ import annotations

import contextlib
import subprocess
import tempfile
import time
import types
from collections.abc import Callable
from pathlib import Path
from typing import cast
from unittest.mock import MagicMock, patch

import pytest

import tests.conftest as _m
from tests.conftest import (
    _CHECKER_SCAN_DIRS,
    _CHECKER_SCRIPT,
    _REPO_ROOT,
    _SUMMARY_LINE,
    CheckerResult,
    _cached_checker_results,
    _cleanup_stale_temp_files,
    _compute_checker_hash,
)

# ============================================================================
# Existing tests (S13–S16)
# ============================================================================


def test_cached_checker_results_runs_once_per_mode() -> None:
    """S13: _cached_checker_results calls subprocess.run exactly 3 times.

    Mocks subprocess.run to avoid executing the real checker script,
    then verifies the fixture makes one call per mode (canonical,
    boundary, root) and returns a mapping with all 3 keys.

    Uses ``__wrapped__`` to access the underlying function bypassing
    pytest's direct-call guard, enabling controlled mocking.
    """
    fake_proc = subprocess.CompletedProcess(
        args=[], returncode=0, stdout=_SUMMARY_LINE, stderr=""
    )
    cached_fn = cast(
        Callable[[], types.MappingProxyType[str, CheckerResult]],
        _cached_checker_results.__wrapped__,  # pyright: ignore[reportUnknownMemberType, reportAttributeAccessIssue]
    )
    with patch("subprocess.run", return_value=fake_proc) as mock_run:
        result = cached_fn()

    assert cast(MagicMock, mock_run).call_count == 3
    assert set(result.keys()) == {"canonical", "boundary", "root"}
    for mode in ("canonical", "boundary", "root"):
        value = result[mode]
        assert isinstance(value, tuple)  # CheckerResult is a NamedTuple
        assert value.returncode == 0
    assert "VIOLATION" not in result["canonical"].stdout
    assert "All test hardcode checks passed" in result["canonical"].stdout


def test_checker_result_provides_cached_access(
    checker_result: Callable[..., CheckerResult],
) -> None:
    """S14: checker_result returns cached CheckerResult per mode.

    Verifies individual mode access, 'all' composition (max returncode,
    concatenated stdout), and ValueError for invalid modes.
    """
    for mode in ("canonical", "boundary", "root"):
        result = checker_result(mode)
        assert isinstance(result, tuple)  # CheckerResult is a NamedTuple
        assert result.returncode == 0

    all_result = checker_result("all")
    assert isinstance(all_result, tuple)  # CheckerResult is a NamedTuple
    assert all_result.returncode == 0
    assert "All test hardcode checks passed" in all_result.stdout

    with pytest.raises(ValueError, match="Unknown checker mode"):
        checker_result("invalid_mode")


def test_cleanup_stale_temp_files_removes_leftovers() -> None:
    """S15: _cleanup_stale_temp_files removes tmp*.py leftovers.

    Creates a temporary file matching the cleanup pattern, invokes
    the cleanup function directly via ``__wrapped__``, and verifies
    the file is removed.
    """
    cleanup_fn = cast(
        Callable[[], None],
        _cleanup_stale_temp_files.__wrapped__,  # pyright: ignore[reportUnknownMemberType, reportAttributeAccessIssue]
    )
    stale_file = _REPO_ROOT / "tests" / "tmp_test_leftover.py"
    try:
        stale_file.write_text("# stale leftover from crashed session\n")
        assert stale_file.exists()
        cleanup_fn()
        assert not stale_file.exists()
    finally:
        if stale_file.exists():
            stale_file.unlink(missing_ok=True)


def test_compute_checker_hash_reflects_file_changes() -> None:
    """S16: _compute_checker_hash changes when scanned files change.

    Verifies determinism (same hash on repeated calls), sensitivity
    (hash changes when a .py file is added to a scan dir), and
    restoration (hash returns to baseline after file removal).
    """
    hash_before = _compute_checker_hash()
    hash_repeat = _compute_checker_hash()
    assert hash_before == hash_repeat

    probe_file = _REPO_ROOT / "tests" / "unit" / "_hash_probe_test.py"
    try:
        probe_file.write_text("# hash probe\n")
        hash_after_add = _compute_checker_hash()
        assert hash_after_add != hash_before
    finally:
        probe_file.unlink(missing_ok=True)

    hash_after_remove = _compute_checker_hash()
    assert hash_after_remove == hash_before


# ============================================================================
# Hash coverage tests (S35–S38)
# ============================================================================


def test_hash_covers_script_content(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """S35: Hash changes when the checker script content changes.

    Creates a temporary copy of the checker script with an appended
    comment line, monkeypatches ``_CHECKER_SCRIPT`` in
    ``tests.conftest`` to point to the copy, and verifies that
    ``_compute_checker_hash()`` returns a different hash than the
    baseline.
    """
    baseline = _compute_checker_hash()

    temp_script = tmp_path / "check-test-hardcodes.sh"
    temp_script.write_text(_CHECKER_SCRIPT.read_text() + "\n# appended comment\n")
    monkeypatch.setattr(_m, "_CHECKER_SCRIPT", temp_script)

    new_hash = _compute_checker_hash()
    assert baseline != new_hash, "Hash must change when the script content changes"


def test_hash_covers_scanned_test_files() -> None:
    """S36: Hash changes when a new .py file appears in a scanned directory.

    Creates a temporary ``.py`` file in the first scan directory
    (``tests/unit/``), verifies the hash changes, and cleans up in
    a ``finally`` block.
    """
    baseline = _compute_checker_hash()

    scan_dir = _REPO_ROOT / _CHECKER_SCAN_DIRS[0]
    assert scan_dir.is_dir(), f"Scan directory {scan_dir} does not exist"

    with tempfile.NamedTemporaryFile(
        suffix=".py", dir=str(scan_dir), delete=False
    ) as f:
        f.write(b"# auto-generated test probe file\n_UNIQUE_MARKER = 68693\n")
        temp_path = Path(f.name)

    try:
        new_hash = _compute_checker_hash()
        assert (
            baseline != new_hash
        ), "Hash must change when a new .py file appears in a scanned directory"
    finally:
        temp_path.unlink(missing_ok=True)


def test_hash_excludes_pycache() -> None:
    """S37: Hash excludes ``__pycache__`` entries.

    Creates a ``.py`` file inside a ``__pycache__/`` directory within
    a scan directory and verifies the hash does NOT change, confirming
    that ``_compute_checker_hash()`` skips ``__pycache__/`` entries
    via the ``"__pycache__" in py_file.parts`` check.
    """
    baseline = _compute_checker_hash()

    scan_dir = _REPO_ROOT / _CHECKER_SCAN_DIRS[0]
    assert scan_dir.is_dir(), f"Scan directory {scan_dir} does not exist"

    pycache_dir = scan_dir / "__pycache__"
    pycache_dir.mkdir(exist_ok=True)
    pyc_file = pycache_dir / "dummy.py"
    pyc_file.write_text("# pycache exclusion probe\n")

    try:
        after_pycache = _compute_checker_hash()
        assert (
            after_pycache == baseline
        ), "__pycache__ entries must be excluded from the hash"
    finally:
        pyc_file.unlink(missing_ok=True)
        with contextlib.suppress(OSError):
            pycache_dir.rmdir()


def test_hash_excludes_init_py() -> None:
    """S37b: Hash excludes ``__init__.py`` files.

    Creates a temporary subdirectory with an ``__init__.py`` file in a
    scan directory and verifies the hash does NOT change, confirming
    that ``_compute_checker_hash()`` skips ``__init__.py`` files via
    the ``py_file.name == "__init__.py"`` check.
    """
    baseline = _compute_checker_hash()

    scan_dir = _REPO_ROOT / _CHECKER_SCAN_DIRS[0]
    assert scan_dir.is_dir(), f"Scan directory {scan_dir} does not exist"

    sub_dir = scan_dir / "_init_probe_subdir"
    sub_dir.mkdir(exist_ok=True)
    init_file = sub_dir / "__init__.py"
    init_file.write_text("# init exclusion probe\n")

    try:
        after_init = _compute_checker_hash()
        assert (
            after_init == baseline
        ), "__init__.py files must be excluded from the hash"
    finally:
        init_file.unlink(missing_ok=True)
        with contextlib.suppress(OSError):
            sub_dir.rmdir()


def test_hash_deterministic() -> None:
    """S38: ``_compute_checker_hash()`` returns the same value on repeated calls."""
    hash1 = _compute_checker_hash()
    hash2 = _compute_checker_hash()
    assert hash1 == hash2, "Hash must be deterministic across calls"


# ============================================================================
# Performance budget tests (S39–S40)
# ============================================================================


def test_hash_within_subsecond_budget() -> None:
    """S39: ``_compute_checker_hash()`` completes in under 1.0 seconds.

    Uses ``time.perf_counter()`` to measure elapsed wall-clock time
    for a single hash computation call and asserts it stays within
    the 1-second budget.
    """
    start = time.perf_counter()
    _ = _compute_checker_hash()
    elapsed = time.perf_counter() - start
    assert elapsed < 1.0, f"Hash computation took {elapsed:.3f}s, budget is 1.0s"


def test_cache_startup_within_budget(
    request: pytest.FixtureRequest,
) -> None:
    """S40: First access to ``_cached_checker_results`` completes in under 10s.

    This covers up to 3 subprocess invocations of the checker script.
    If the session fixture is already cached (resolved by a prior test),
    the elapsed time will be near-zero — the 10s budget is a ceiling
    for the cold-cache scenario.
    """
    start = time.perf_counter()
    _ = request.getfixturevalue("_cached_checker_results")
    elapsed = time.perf_counter() - start
    assert elapsed < 10.0, f"Cache startup took {elapsed:.3f}s, budget is 10.0s"


# ============================================================================
# Subprocess comparison test (S41)
# ============================================================================


def test_checker_result_all_matches_direct_subprocess(
    checker_result: Callable[..., CheckerResult],
) -> None:
    """S41: ``checker_result("all")`` matches a fresh direct subprocess invocation.

    Calls ``checker_result("all")`` (cached composition) and compares
    its returncode, stdout, and stderr to a fresh
    ``subprocess.run(["bash", str(_CHECKER_SCRIPT), "all"], ...)``
    call, verifying that the cached composition is equivalent to
    running the checker script directly in ``all`` mode.
    """
    result = checker_result("all")
    proc = subprocess.run(  # noqa: S603
        ["bash", str(_CHECKER_SCRIPT), "all"],
        capture_output=True,
        text=True,
        cwd=str(_REPO_ROOT),
        timeout=60,
    )
    assert (
        result.returncode == proc.returncode
    ), f"returncode mismatch: {result.returncode} != {proc.returncode}"
    assert result.stdout == proc.stdout, "stdout mismatch"
    assert result.stderr == proc.stderr, "stderr mismatch"
