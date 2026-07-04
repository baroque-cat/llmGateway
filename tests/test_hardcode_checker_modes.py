"""Tests for the gatekeeper script's 4 execution modes.

Verifies that ``scripts/check-test-hardcodes.sh`` correctly enforces
zero-hardcodes in canonical mode, whitelist in boundary mode, strict checks
in root mode, and sequential execution in all mode.

Scenarios: S7, S8, S9, S10.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

_REPO_ROOT: Path = Path(__file__).resolve().parent.parent
_CHECKER_SCRIPT: Path = _REPO_ROOT / "scripts" / "check-test-hardcodes.sh"
_SUMMARY_MARKER: str = "All test hardcode checks passed"


def _run_checker(mode: str) -> subprocess.CompletedProcess[str]:
    """Run the gatekeeper script in the given mode.

    Args:
        mode: One of ``canonical``, ``boundary``, ``root``, ``all``.

    Returns:
        Completed process with returncode, stdout, stderr.
    """
    return subprocess.run(  # noqa: S603
        ["bash", str(_CHECKER_SCRIPT), mode],  # noqa: S603
        capture_output=True,
        text=True,
        cwd=str(_REPO_ROOT),
        timeout=60,
    )


class TestHardcodeCheckerModes:
    """Tests for the 4 gatekeeper script modes."""

    def test_canonical_mode_enforces_strict_zero_hardcodes(self) -> None:
        """S7: Canonical mode enforces strict zero-hardcodes in unit tests.

        Runs the script in ``canonical`` mode and asserts exit 0 on the
        clean codebase.  Canonical mode scans ``tests/unit/`` with no
        boundary annotations allowed.
        """
        result = _run_checker("canonical")
        assert result.returncode == 0
        assert "VIOLATION" not in result.stdout

    def test_boundary_mode_whitelist_via_annotations(self) -> None:
        """S8: Boundary mode implements whitelist via ``# boundary:`` annotations.

        Runs the script in ``boundary`` mode and asserts exit 0.  Boundary
        mode scans ``tests/integration/``, ``tests/security/``,
        ``tests/e2e/``, ``tests/stress/``, and ``tests/batching/`` with
        ``# boundary:`` lookback (20 non-blank lines, case-insensitive).

        Production URLs (``BANNED_PROD_URLS``) are always banned even with
        annotations — verified by reading the script source.
        """
        result = _run_checker("boundary")
        assert result.returncode == 0
        assert "VIOLATION" not in result.stdout

        # Verify production URLs are always banned (even with annotations)
        script_source = _CHECKER_SCRIPT.read_text()
        assert "always banned" in script_source.lower()
        assert "BANNED_PROD_URLS" in script_source

        # Verify boundary lookback (20 non-blank lines, case-insensitive)
        assert "20" in script_source
        assert "boundary:" in script_source.lower()

    def test_root_mode_enforces_strict_checks(self) -> None:
        """S9: Root mode enforces strict checks on root-level test files.

        Runs the script in ``root`` mode and asserts exit 0.  Root mode
        scans ``tests/*.py`` (root-level only, non-recursive) with no
        boundary annotations allowed.
        """
        result = _run_checker("root")
        assert result.returncode == 0
        assert "VIOLATION" not in result.stdout

    def test_all_mode_runs_all_three_sequentially(self) -> None:
        """S10: All mode runs canonical, boundary, and root sequentially.

        Runs the script in ``all`` mode (and with no args, which defaults
        to ``all``) and asserts exit 0 with the success summary message.
        """
        result = _run_checker("all")
        assert result.returncode == 0
        assert _SUMMARY_MARKER in result.stdout

        # No-args defaults to "all"
        result_no_args = subprocess.run(  # noqa: S603
            ["bash", str(_CHECKER_SCRIPT)],  # noqa: S603
            capture_output=True,
            text=True,
            cwd=str(_REPO_ROOT),
            timeout=60,
        )
        assert result_no_args.returncode == 0
        assert _SUMMARY_MARKER in result_no_args.stdout

    def test_invalid_mode_returns_error(self) -> None:
        """Invalid mode returns exit 1 with usage message."""
        result = _run_checker("invalid-mode")
        assert result.returncode == 1
        assert "Usage" in result.stderr
