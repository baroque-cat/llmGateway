"""Gatekeeper tests — production URLs are ALWAYS banned everywhere.

Validates that ``scripts/check-test-hardcodes.sh`` enforces the rule that
production API URLs (``BANNED_PROD_URLS``) are always banned in every mode
— canonical, boundary, root, and all — regardless of directory or
``# boundary:`` annotations.

Production URL strings in THIS file are constructed via concatenation so
the checker's own root-mode scan does not flag this source file. The
boundary annotation literal is likewise concatenated to avoid any
annotation detector.

An external process (e.g., an LSP file watcher) may intermittently delete
newly-created ``.py`` files in the test tree. The ``_probe_checker``
helper retries the create-check-cleanup cycle so that transient file
deletion does not cause flaky failures.

Scenarios: S11, S12, S13, S14, S15, S16.
"""

# pyright: reportPrivateUsage=false
# Imports private names (``_CHECKER_SCRIPT``, ``_REPO_ROOT``) from the
# project's own ``tests.conftest`` — same pattern as
# ``test_hardcode_checker_regression.py``.

from __future__ import annotations

import contextlib
import os
import subprocess
import tempfile
import time
from pathlib import Path

import pytest

from tests.conftest import _CHECKER_SCRIPT, _REPO_ROOT

# ── Production URLs (concatenated to avoid self-flagging) ──
# All 6 entries of BANNED_PROD_URLS, split so the literal full URL never
# appears in this source file (preventing root-mode self-detection).

_PROD_URL_PARTS: list[tuple[str, str]] = [
    ("https://generativelanguage.googlea", "pis.com"),
    ("https://api.anthropic", ".com"),
    ("https://api.deep", "seek.com"),
    ("https://dashscope.aliyuncs", ".com"),
    ("https://api.open", "ai.com"),
    ("https://api.gr", "oq.com"),
]

_PROD_URLS: list[str] = [head + tail for head, tail in _PROD_URL_PARTS]

_PROD_URL_LABELS: list[str] = [
    "gemini",
    "anthropic",
    "deepseek",
    "dashscope",
    "openai",
    "groq",
]

# The OpenAI production URL used by scenarios S11–S15.
_OPENAI_URL: str = _PROD_URL_PARTS[4][0] + _PROD_URL_PARTS[4][1]

# The boundary annotation literal — concatenated to avoid the annotation
# detector in root mode.
_BOUNDARY_ANNO: str = "#" + " boundary:"

# Retry configuration for ``_probe_checker``. An external LSP file watcher
# may intermittently delete temp ``.py`` files before the checker scans
# them; retrying makes the tests resilient to this interference.
_MAX_ATTEMPTS: int = 7
_RETRY_DELAY: float = 0.5


# ── Helpers ──


def _run_script(mode: str) -> subprocess.CompletedProcess[str]:
    """Run the hardcode checker script in the given mode.

    Args:
        mode: One of ``canonical``, ``boundary``, ``root``, or ``all``.

    Returns:
        The completed subprocess with captured stdout and stderr.
    """
    return subprocess.run(
        ["bash", str(_CHECKER_SCRIPT), mode],
        capture_output=True,
        text=True,
        cwd=str(_REPO_ROOT),
        timeout=30,
    )


def _make_temp_py(content: str, target_dir: Path) -> Path:
    """Create a temporary ``.py`` file with *content* in *target_dir*.

    Uses the ``_gate_synth_`` prefix so the session-scoped cleanup fixture
    (which removes ``tmp*.py`` files) does not touch it. The caller must
    unlink the returned path in a ``try/finally`` block.

    Args:
        content: Source text to write into the temp file.
        target_dir: Directory in which to place the file (must exist).

    Returns:
        Absolute path to the created file.
    """
    with tempfile.NamedTemporaryFile(
        mode="w",
        suffix=".py",
        prefix="_gate_synth_",
        dir=str(target_dir),
        delete=False,
        encoding="utf-8",
    ) as tmp:
        tmp.write(content)
        name = tmp.name
    assert isinstance(name, str)
    return Path(name)


def _probe_checker(
    content: str,
    target_dir: Path,
    mode: str,
) -> subprocess.CompletedProcess[str]:
    """Create a temp file, run the checker, and clean up — with retry.

    Encapsulates the create → check → unlink cycle. Retries when an
    external process (e.g., an LSP file watcher) deletes the temp file
    before the checker can scan it, so that transient file deletion does
    not produce flaky failures.

    The result is trustworthy when either (a) the checker reported a
    violation (non-zero exit) or (b) the temp file survived the run
    (meaning a zero exit is a genuine no-violation, not a missed scan).

    Args:
        content: Source text to write into the temp file.
        target_dir: Directory in which to place the file.
        mode: Checker mode (``canonical``, ``boundary``, ``root``, ``all``).

    Returns:
        The completed subprocess result for the caller to assert on.
    """
    result: subprocess.CompletedProcess[str] | None = None
    for _attempt in range(_MAX_ATTEMPTS):
        tmp_path = _make_temp_py(content, target_dir)
        try:
            if not tmp_path.exists():
                time.sleep(_RETRY_DELAY)
                continue
            result = _run_script(mode)
            if result.returncode != 0 or tmp_path.exists():
                return result
            # File was deleted during the checker run — result is
            # untrustworthy. Wait briefly and retry.
            time.sleep(_RETRY_DELAY)
        finally:
            with contextlib.suppress(FileNotFoundError):
                os.unlink(tmp_path)
    if result is not None:
        return result
    return _run_script(mode)


# ── S11: Canonical mode detects production URL ──


def test_canonical_detects_production_url() -> None:
    """S11: Canonical mode exits non-zero when ``tests/unit/`` has a production URL.

    Places a temp ``.py`` file containing the OpenAI production URL in
    ``tests/unit/``, runs the checker in ``canonical`` mode, and asserts a
    non-zero exit code with a ``CANONICAL VIOLATION`` message.
    """
    target = _REPO_ROOT / "tests" / "unit"
    content = (
        '"""Temp file with a banned production URL."""\n'
        f'_BASE_URL = "{_OPENAI_URL}/v1"\n'
    )
    result = _probe_checker(content, target, "canonical")
    assert result.returncode != 0, (
        f"Canonical mode should exit non-zero for production URL. "
        f"returncode={result.returncode}\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    combined = result.stdout + result.stderr
    assert (
        "CANONICAL VIOLATION" in combined
    ), f"Output should mention CANONICAL VIOLATION. Got:\n{combined}"


# ── S12: Boundary mode detects production URL ──


def test_boundary_detects_production_url() -> None:
    """S12: Boundary mode exits non-zero when a boundary dir has a production URL.

    Places a temp ``.py`` file containing the OpenAI production URL in
    ``tests/integration/``, runs the checker in ``boundary`` mode, and
    asserts a non-zero exit code with a ``BOUNDARY VIOLATION`` message
    including the ``always banned`` qualifier.
    """
    target = _REPO_ROOT / "tests" / "integration"
    content = (
        '"""Temp file with a banned production URL."""\n'
        f'_BASE_URL = "{_OPENAI_URL}/v1"\n'
    )
    result = _probe_checker(content, target, "boundary")
    assert result.returncode != 0, (
        f"Boundary mode should exit non-zero for production URL. "
        f"returncode={result.returncode}\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    combined = result.stdout + result.stderr
    assert (
        "BOUNDARY VIOLATION" in combined
    ), f"Output should mention BOUNDARY VIOLATION. Got:\n{combined}"
    assert (
        "always banned" in combined
    ), f"Output should mention 'always banned'. Got:\n{combined}"


# ── S13: Boundary mode rejects production URL even WITH annotation ──


def test_boundary_rejects_url_even_with_annotation() -> None:
    """S13: Boundary mode still bans production URLs even with ``# boundary:``.

    Places a temp ``.py`` file in ``tests/integration/`` containing the
    OpenAI production URL on a line annotated with ``# boundary:``, runs
    the checker in ``boundary`` mode, and asserts a non-zero exit code with
    the ``always banned`` qualifier — confirming annotations never exempt
    production URLs.
    """
    target = _REPO_ROOT / "tests" / "integration"
    content = (
        '"""Temp file — annotation must NOT exempt production URLs."""\n'
        f'_BASE_URL = "{_OPENAI_URL}/v1"  {_BOUNDARY_ANNO} legit usage\n'
    )
    result = _probe_checker(content, target, "boundary")
    assert result.returncode != 0, (
        f"Production URL should STILL be banned even with boundary "
        f"annotation. returncode={result.returncode}\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    combined = result.stdout + result.stderr
    assert (
        "always banned" in combined
    ), f"Output should mention 'always banned'. Got:\n{combined}"


# ── S14: Root mode detects production URL ──


def test_root_detects_production_url() -> None:
    """S14: Root mode exits non-zero when ``tests/`` root has a production URL.

    Places a temp ``.py`` file at the ``tests/`` root level containing the
    OpenAI production URL, runs the checker in ``root`` mode, and asserts a
    non-zero exit code with a ``ROOT VIOLATION`` message.
    """
    target = _REPO_ROOT / "tests"
    content = (
        '"""Temp file at root with a banned production URL."""\n'
        f'_BASE_URL = "{_OPENAI_URL}/v1"\n'
    )
    result = _probe_checker(content, target, "root")
    assert result.returncode != 0, (
        f"Root mode should exit non-zero for production URL. "
        f"returncode={result.returncode}\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    combined = result.stdout + result.stderr
    assert (
        "ROOT VIOLATION" in combined
    ), f"Output should mention ROOT VIOLATION. Got:\n{combined}"


# ── S15: "all" mode detects production URL in canonical dir ──


def test_all_mode_detects_url_in_canonical_dir() -> None:
    """S15: ``all`` mode detects a production URL placed in a canonical directory.

    Places a temp ``.py`` file containing the OpenAI production URL in
    ``tests/unit/``, runs the checker in ``all`` mode, and asserts a
    non-zero exit code with a violation detected in the combined output.
    """
    target = _REPO_ROOT / "tests" / "unit"
    content = (
        '"""Temp file with a banned production URL."""\n'
        f'_BASE_URL = "{_OPENAI_URL}/v1"\n'
    )
    result = _probe_checker(content, target, "all")
    assert result.returncode != 0, (
        f"All mode should exit non-zero for production URL in unit/. "
        f"returncode={result.returncode}\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    combined = result.stdout + result.stderr
    assert (
        "VIOLATION" in combined
    ), f"Output should mention a VIOLATION. Got:\n{combined}"


# ── S16: All 6 production URLs are detected (parametrized) ──


@pytest.mark.parametrize(
    "prod_url,label",
    list(zip(_PROD_URLS, _PROD_URL_LABELS, strict=True)),
    ids=_PROD_URL_LABELS,
)
def test_all_urls_in_banned_list_detected(prod_url: str, label: str) -> None:
    """S16: Each of the 6 production URLs is detected by canonical mode.

    Parametrized over every entry in ``BANNED_PROD_URLS``. For each URL, a
    temp ``.py`` file is placed in ``tests/unit/``, the checker runs in
    ``canonical`` mode, and a non-zero exit code with a ``CANONICAL
    VIOLATION`` message is asserted.

    Args:
        prod_url: A production URL constructed via string concatenation.
        label: Short human-readable label for the parametrize ID.
    """
    target = _REPO_ROOT / "tests" / "unit"
    content = (
        '"""Temp file with a banned production URL."""\n'
        f'_BASE_URL = "{prod_url}/v1"\n'
    )
    result = _probe_checker(content, target, "canonical")
    assert result.returncode != 0, (
        f"Canonical mode should detect production URL ({label}). "
        f"returncode={result.returncode}\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    combined = result.stdout + result.stderr
    assert "CANONICAL VIOLATION" in combined, (
        f"Output should mention CANONICAL VIOLATION for {label}. " f"Got:\n{combined}"
    )
