"""Tests for gatekeeper cache fixtures and helpers in tests/conftest.py.

Verifies the caching, composition, cleanup, and hash-detection behavior
of the session-scoped checker fixtures and private helper functions.

Scenarios:
  S13: _cached_checker_results runs subprocess.run once per mode (3 calls).
  S14: checker_result provides cached access and composes 'all' mode.
  S15: _cleanup_stale_temp_files removes leftover tmp*.py files.
  S16: _compute_checker_hash reflects file additions/removals.
"""

# pyright: reportPrivateUsage=false

import subprocess
import types
from collections.abc import Callable
from typing import cast
from unittest.mock import MagicMock, patch

import pytest

from tests.conftest import (
    _REPO_ROOT,
    _SUMMARY_LINE,
    CheckerResult,
    _cached_checker_results,
    _cleanup_stale_temp_files,
    _compute_checker_hash,
)


class TestCheckerCacheFixtures:
    """Tests for gatekeeper cache fixtures and helpers in conftest.py."""

    def test_cached_checker_results_runs_once_per_mode(self) -> None:
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
        self, checker_result: Callable[..., CheckerResult]
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

    def test_cleanup_stale_temp_files_removes_leftovers(self) -> None:
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

    def test_compute_checker_hash_reflects_file_changes(self) -> None:
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
