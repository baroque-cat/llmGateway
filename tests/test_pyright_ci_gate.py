#!/usr/bin/env python3
"""CI gate tests for the tiered pyright strictness configuration.

Verifies that ``poetry run pyright`` exits zero with zero errors after the
tiered strictness configuration was applied.

Test Group: G5 (gatekeeper structural tests).
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

_REPO_ROOT: Path = Path(__file__).resolve().parent.parent


@pytest.mark.meta
class TestPyrightCiGate:
    """CI gate tests verifying pyright tiering configuration."""

    def test_pyright_exits_zero_after_tiering(self) -> None:
        """Verify ``poetry run pyright`` exits 0 with zero errors after tiering.

        Scenario: #10 — pyright CI gate after tiered strictness configuration.
        WHEN: ``poetry run pyright`` is invoked with no path arguments on the
              actual project (cwd = repo root).
        THEN: The subprocess exits with return code 0 AND the output summary
              reports zero errors (not just zero warnings — zero errors).
        """
        result = subprocess.run(
            ["poetry", "run", "pyright"],
            capture_output=True,
            text=True,
            timeout=120,
            cwd=str(_REPO_ROOT),
        )

        assert result.returncode == 0, (
            f"pyright exited with code {result.returncode}:\n"
            f"stdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}"
        )

        # Parse the pyright summary line, e.g. "0 errors, 0 warnings, 0
        # informations".  Search both stdout and stderr to be robust.
        combined_output = result.stdout + result.stderr
        error_match = re.search(r"(\d+) errors, (\d+) warnings", combined_output)
        assert error_match is not None, (
            "Could not parse error count from pyright output:\n" f"{combined_output}"
        )
        error_count = int(error_match.group(1))
        assert error_count == 0, (
            f"pyright reported {error_count} errors (expected 0):\n"
            f"{combined_output}"
        )
