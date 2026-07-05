"""Tier 2 synthetic gatekeeper tests for ``scripts/check-test-hardcodes.sh``.

Tests the core mode-specific behaviour of the hardcode checker by creating
synthetic violation files in the appropriate test subdirectories, invoking
the checker, and asserting exit codes and output content.

Scenarios: S1-S10.

IMPORTANT: This file's source code deliberately uses string concatenation
for banned patterns (e.g. ``'"gpt-' + '4"'``) so the checker's own root-mode
scan does not flag this infrastructure file.  The file is also listed in
``EXCLUDE_FILES`` in the checker script for belt-and-suspenders safety.
"""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

from tests.conftest import (
    _CHECKER_SCRIPT,  # pyright: ignore[reportPrivateUsage]
    _REPO_ROOT,  # pyright: ignore[reportPrivateUsage]
)

# ── Banned patterns (string-concatenated to avoid self-triggering) ────────

_BANNED_URL: str = "https://api.open" + "ai.com"
_BANNED_SECRET: str = "your_secure_password_" + "here"
_BANNED_DB_PARAM: str = "DB_USER=llm_gate" + "way"
_BANNED_MODEL: str = '"gpt-' + '4"'
_BANNED_PROVIDER_TYPE: str = "provider_type = " + '"open' + 'ai"'
_BOUNDARY_ANNO: str = "#" + " boundary:"

# ── Scan directories ──────────────────────────────────────────────────────

_UNIT_DIR: Path = _REPO_ROOT / "tests" / "unit"
_INTEGRATION_DIR: Path = _REPO_ROOT / "tests" / "integration"
_TESTS_ROOT: Path = _REPO_ROOT / "tests"


# ── Helpers ────────────────────────────────────────────────────────────────


def _run_checker(mode: str) -> subprocess.CompletedProcess[str]:
    """Run the hardcode checker script with *mode* and return the result.

    Args:
        mode: One of ``canonical``, ``boundary``, ``root``, ``all``.

    Returns:
        Completed process with returncode, stdout, and stderr.
    """
    return subprocess.run(  # noqa: S603
        ["bash", str(_CHECKER_SCRIPT), mode],  # noqa: S603
        capture_output=True,
        text=True,
        cwd=str(_REPO_ROOT),
        timeout=30,
    )


def _make_temp_py(directory: Path, content: str) -> str:
    """Create a temp ``.py`` file with *content* in *directory*.

    Uses a ``_gate_synth_`` prefix (not ``tmp``) to avoid being deleted by
    the ``_cleanup_stale_temp_files`` session fixture in ``conftest.py``,
    which removes all ``tmp*.py`` files as environmental hygiene.

    Args:
        directory: Target scan directory for the temp file.
        content: String content to write to the file.

    Returns:
        Absolute path to the created temp file.  Caller is responsible for
        cleanup via ``Path(path).unlink(missing_ok=True)``.
    """
    tmp = tempfile.NamedTemporaryFile(  # noqa: SIM115
        mode="w",
        prefix="_gate_synth_",
        suffix=".py",
        dir=str(directory),
        delete=False,
        encoding="utf-8",
    )
    try:
        tmp.write(content)
        tmp.close()
        return tmp.name
    except Exception:
        tmp.close()
        Path(tmp.name).unlink(missing_ok=True)
        raise


# ═══════════════════════════════════════════════════════════════════════════
# CANONICAL MODE TESTS (S1 – S5)
# ═══════════════════════════════════════════════════════════════════════════


def test_canonical_detects_banned_production_url() -> None:
    """S1: Canonical mode detects a banned production URL in ``tests/unit/``.

    Creates a temp ``.py`` file containing a banned production API URL,
    runs the checker in ``canonical`` mode, and asserts a non-zero exit
    code with ``CANONICAL VIOLATION`` in stdout.
    """
    content = f'_URL = "{_BANNED_URL}"\n'
    tmp_path = _make_temp_py(_UNIT_DIR, content)
    try:
        result = _run_checker("canonical")
        assert result.returncode != 0, (
            f"Canonical mode should exit non-zero for banned URL.\n"
            f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
        )
        assert "CANONICAL VIOLATION" in result.stdout, (
            f"Expected CANONICAL VIOLATION in stdout.\n" f"STDOUT:\n{result.stdout}"
        )
    finally:
        Path(tmp_path).unlink(missing_ok=True)


def test_canonical_detects_banned_secret() -> None:
    """S2: Canonical mode detects a banned placeholder secret in ``tests/unit/``.

    Creates a temp ``.py`` file containing a banned placeholder secret,
    runs the checker in ``canonical`` mode, and asserts a non-zero exit
    code with ``CANONICAL VIOLATION`` in stdout.
    """
    content = f'_SECRET = "{_BANNED_SECRET}"\n'
    tmp_path = _make_temp_py(_UNIT_DIR, content)
    try:
        result = _run_checker("canonical")
        assert result.returncode != 0, (
            f"Canonical mode should exit non-zero for banned secret.\n"
            f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
        )
        assert "CANONICAL VIOLATION" in result.stdout, (
            f"Expected CANONICAL VIOLATION in stdout.\n" f"STDOUT:\n{result.stdout}"
        )
    finally:
        Path(tmp_path).unlink(missing_ok=True)


def test_canonical_detects_banned_db_param() -> None:
    """S3: Canonical mode detects a banned DB parameter in ``tests/unit/``.

    Creates a temp ``.py`` file containing a banned database parameter,
    runs the checker in ``canonical`` mode, and asserts a non-zero exit
    code with ``CANONICAL VIOLATION`` in stdout.
    """
    content = f'_PARAM = "{_BANNED_DB_PARAM}"\n'
    tmp_path = _make_temp_py(_UNIT_DIR, content)
    try:
        result = _run_checker("canonical")
        assert result.returncode != 0, (
            f"Canonical mode should exit non-zero for banned DB param.\n"
            f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
        )
        assert "CANONICAL VIOLATION" in result.stdout, (
            f"Expected CANONICAL VIOLATION in stdout.\n" f"STDOUT:\n{result.stdout}"
        )
    finally:
        Path(tmp_path).unlink(missing_ok=True)


def test_canonical_detects_banned_model() -> None:
    """S4: Canonical mode detects a banned model name in ``tests/unit/``.

    Creates a temp ``.py`` file containing a banned obsolete model name
    (constructed via string concatenation to avoid self-triggering), runs
    the checker in ``canonical`` mode, and asserts a non-zero exit code
    with ``CANONICAL VIOLATION`` in stdout.
    """
    content = f"_MODEL = {_BANNED_MODEL}\n"
    tmp_path = _make_temp_py(_UNIT_DIR, content)
    try:
        result = _run_checker("canonical")
        assert result.returncode != 0, (
            f"Canonical mode should exit non-zero for banned model.\n"
            f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
        )
        assert "CANONICAL VIOLATION" in result.stdout, (
            f"Expected CANONICAL VIOLATION in stdout.\n" f"STDOUT:\n{result.stdout}"
        )
    finally:
        Path(tmp_path).unlink(missing_ok=True)


def test_canonical_detects_banned_provider_type() -> None:
    """S5: Canonical mode detects a banned provider type in ``tests/unit/``.

    Creates a temp ``.py`` file containing a banned provider type
    assignment (constructed via string concatenation to avoid
    self-triggering), runs the checker in ``canonical`` mode, and asserts
    a non-zero exit code with ``CANONICAL VIOLATION`` in stdout.
    """
    content = f"{_BANNED_PROVIDER_TYPE}\n"
    tmp_path = _make_temp_py(_UNIT_DIR, content)
    try:
        result = _run_checker("canonical")
        assert result.returncode != 0, (
            f"Canonical mode should exit non-zero for banned provider type.\n"
            f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
        )
        assert "CANONICAL VIOLATION" in result.stdout, (
            f"Expected CANONICAL VIOLATION in stdout.\n" f"STDOUT:\n{result.stdout}"
        )
    finally:
        Path(tmp_path).unlink(missing_ok=True)


# ═══════════════════════════════════════════════════════════════════════════
# BOUNDARY MODE TESTS (S6 – S8)
# ═══════════════════════════════════════════════════════════════════════════


def test_boundary_allows_with_annotation() -> None:
    """S6: Boundary mode allows a banned pattern with ``# boundary:`` annotation.

    Creates a temp ``.py`` file in ``tests/integration/`` containing a
    banned model name on the same line as a ``# boundary:`` annotation,
    runs the checker in ``boundary`` mode, and asserts exit 0.
    """
    content = f"_MODEL = {_BANNED_MODEL}  {_BOUNDARY_ANNO} allowed\n"
    tmp_path = _make_temp_py(_INTEGRATION_DIR, content)
    try:
        result = _run_checker("boundary")
        assert result.returncode == 0, (
            f"Boundary mode should exit 0 when banned pattern has "
            f"a boundary annotation.\n"
            f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
        )
    finally:
        Path(tmp_path).unlink(missing_ok=True)


def test_boundary_rejects_without_annotation() -> None:
    """S7: Boundary mode rejects a banned pattern without annotation.

    Creates a temp ``.py`` file in ``tests/integration/`` containing a
    banned model name with no ``# boundary:`` annotation, runs the
    checker in ``boundary`` mode, and asserts a non-zero exit code with
    ``BOUNDARY VIOLATION`` in stdout.
    """
    content = f"_MODEL = {_BANNED_MODEL}\n"
    tmp_path = _make_temp_py(_INTEGRATION_DIR, content)
    try:
        result = _run_checker("boundary")
        assert result.returncode != 0, (
            f"Boundary mode should exit non-zero without annotation.\n"
            f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
        )
        assert "BOUNDARY VIOLATION" in result.stdout, (
            f"Expected BOUNDARY VIOLATION in stdout.\n" f"STDOUT:\n{result.stdout}"
        )
    finally:
        Path(tmp_path).unlink(missing_ok=True)


def test_production_url_always_banned_boundary() -> None:
    """S8: Production URLs are always banned in boundary mode, even with annotation.

    Creates a temp ``.py`` file in ``tests/integration/`` containing a
    banned production URL on the same line as a ``# boundary:`` annotation,
    runs the checker in ``boundary`` mode, and asserts a non-zero exit
    code with ``BOUNDARY VIOLATION`` and ``always banned`` in stdout.
    """
    content = f'_URL = "{_BANNED_URL}"  {_BOUNDARY_ANNO} allowed\n'
    tmp_path = _make_temp_py(_INTEGRATION_DIR, content)
    try:
        result = _run_checker("boundary")
        assert result.returncode != 0, (
            f"Boundary mode should exit non-zero for production URL.\n"
            f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
        )
        assert "BOUNDARY VIOLATION" in result.stdout, (
            f"Expected BOUNDARY VIOLATION in stdout.\n" f"STDOUT:\n{result.stdout}"
        )
        assert "always banned" in result.stdout, (
            f"Expected 'always banned' in stdout.\n" f"STDOUT:\n{result.stdout}"
        )
    finally:
        Path(tmp_path).unlink(missing_ok=True)


# ═══════════════════════════════════════════════════════════════════════════
# ROOT MODE TESTS (S9)
# ═══════════════════════════════════════════════════════════════════════════


def test_root_detects_banned_model() -> None:
    """S9: Root mode detects a banned model name in root-level test files.

    Creates a temp ``.py`` file at the ``tests/`` root containing a banned
    model name (constructed via string concatenation to avoid
    self-triggering), runs the checker in ``root`` mode, and asserts a
    non-zero exit code with ``ROOT VIOLATION`` in stdout.
    """
    content = f"_MODEL = {_BANNED_MODEL}\n"
    tmp_path = _make_temp_py(_TESTS_ROOT, content)
    try:
        result = _run_checker("root")
        assert result.returncode != 0, (
            f"Root mode should exit non-zero for banned model.\n"
            f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
        )
        assert "ROOT VIOLATION" in result.stdout, (
            f"Expected ROOT VIOLATION in stdout.\n" f"STDOUT:\n{result.stdout}"
        )
    finally:
        Path(tmp_path).unlink(missing_ok=True)


# ═══════════════════════════════════════════════════════════════════════════
# ALL MODE TESTS (S10)
# ═══════════════════════════════════════════════════════════════════════════


def test_all_mode_composition() -> None:
    """S10: All mode runs canonical, boundary, and root sequentially.

    Creates temp ``.py`` files in both ``tests/unit/`` and ``tests/`` root
    containing a banned model name (constructed via string concatenation
    to avoid self-triggering), runs the checker in ``all`` mode, and
    asserts violations from multiple modes (``CANONICAL VIOLATION`` and
    ``ROOT VIOLATION``) in stdout.
    """
    content = f"_MODEL = {_BANNED_MODEL}\n"
    unit_tmp = _make_temp_py(_UNIT_DIR, content)
    root_tmp = _make_temp_py(_TESTS_ROOT, content)
    try:
        result = _run_checker("all")
        assert result.returncode != 0, (
            f"All mode should exit non-zero with violations.\n"
            f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
        )
        assert "CANONICAL VIOLATION" in result.stdout, (
            f"Expected CANONICAL VIOLATION from unit/ scan.\n"
            f"STDOUT:\n{result.stdout}"
        )
        assert "ROOT VIOLATION" in result.stdout, (
            f"Expected ROOT VIOLATION from root scan.\n" f"STDOUT:\n{result.stdout}"
        )
    finally:
        Path(unit_tmp).unlink(missing_ok=True)
        Path(root_tmp).unlink(missing_ok=True)


# ═══════════════════════════════════════════════════════════════════════════
# BANNED_OTHER_REGEX / BANNED_OTHER_PCRE TESTS
# ═══════════════════════════════════════════════════════════════════════════


# String-concatenated to avoid self-triggering pattern detection
# Must be on a single line — grep -P .* does NOT match across newlines
_NON_CANONICAL_DB_PASSWORD: str = (
    "DatabaseConfig(" + 'host="x", ' + 'password="not_test_password")'
)

_CANONICAL_DB_PASSWORD: str = (
    "DatabaseConfig(" + 'host="x", ' + 'password="test_password")'
)


def test_canonical_detects_non_canonical_db_password() -> None:
    """Canonical mode detects DatabaseConfig with non-canonical password.

    Creates a temp ``.py`` file in ``tests/unit/`` containing a
    ``DatabaseConfig(...password="not_test_password")`` call,
    runs the checker in ``canonical`` mode, and asserts a non-zero exit
    code with ``CANONICAL VIOLATION`` in stdout.
    """
    tmp_path = _make_temp_py(_UNIT_DIR, _NON_CANONICAL_DB_PASSWORD + "\n")
    try:
        result = _run_checker("canonical")
        assert result.returncode != 0, (
            "Canonical mode should exit non-zero for non-canonical DB password.\n"
            f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
        )
        assert "CANONICAL VIOLATION" in result.stdout, (
            f"Expected CANONICAL VIOLATION in stdout.\n" f"STDOUT:\n{result.stdout}"
        )
    finally:
        Path(tmp_path).unlink(missing_ok=True)


def test_canonical_allows_canonical_db_password() -> None:
    """Canonical mode allows DatabaseConfig with canonical password.

    Creates a temp ``.py`` file in ``tests/unit/`` containing a
    ``DatabaseConfig(...password="test_password")`` call (the canonical
    value), runs the checker in ``canonical`` mode, and asserts exit 0 —
    the negative lookahead ``(?!test_password)`` must NOT flag the
    canonical password.
    """
    tmp_path = _make_temp_py(_UNIT_DIR, _CANONICAL_DB_PASSWORD + "\n")
    try:
        result = _run_checker("canonical")
        assert result.returncode == 0, (
            "Canonical mode should exit 0 for canonical DB password "
            "(lookahead must allow test_password).\n"
            f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
        )
    finally:
        Path(tmp_path).unlink(missing_ok=True)


def test_boundary_detects_non_canonical_db_password() -> None:
    """Boundary mode detects DatabaseConfig with non-canonical password.

    Creates a temp ``.py`` file in ``tests/integration/`` containing a
    ``DatabaseConfig(...password="not_test_password")`` call without a
    ``# boundary:`` annotation, runs the checker in ``boundary`` mode,
    and asserts a non-zero exit code with ``BOUNDARY VIOLATION``.
    """
    tmp_path = _make_temp_py(_INTEGRATION_DIR, _NON_CANONICAL_DB_PASSWORD + "\n")
    try:
        result = _run_checker("boundary")
        assert result.returncode != 0, (
            "Boundary mode should exit non-zero for non-canonical DB password "
            "without annotation.\n"
            f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
        )
        assert "BOUNDARY VIOLATION" in result.stdout, (
            f"Expected BOUNDARY VIOLATION in stdout.\n" f"STDOUT:\n{result.stdout}"
        )
    finally:
        Path(tmp_path).unlink(missing_ok=True)
