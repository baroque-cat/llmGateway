"""Tier 2 synthetic gatekeeper tests for boundary compliance.

Verifies the gatekeeper script's boundary mode, pre-commit hook
configuration, and CI workflow integration.

Scenarios: S25-S34.

IMPORTANT: Banned patterns in this file are constructed via string
concatenation to avoid self-triggering the root-mode checker.  This file
is also listed in ``EXCLUDE_FILES`` in the checker script for
belt-and-suspenders safety.
"""

from __future__ import annotations

import re
import subprocess
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

import pytest
import yaml

from tests.conftest import (
    _CHECKER_SCRIPT,  # pyright: ignore[reportPrivateUsage]
    _REPO_ROOT,  # pyright: ignore[reportPrivateUsage]
    CheckerResult,
)

# ── Runtime-constructed strings (split to avoid self-triggering) ────────────

_BOUNDARY_ANNO: str = "#" + " boundary:"
_BOUNDARY_VIOLATION: str = "BOUNDARY" + " VIOLATION"

# Banned model name patterns (quoted strings, split to avoid self-triggering).
_BANNED_MODEL_PATTERNS: tuple[str, ...] = (
    '"' + "gpt-3.5-turbo" + '"',
    '"' + "gpt-4" + '"',
    '"' + "gpt-4o" + '"',
    '"' + "claude-3-opus" + '"',
    '"' + "gemini-pro" + '"',
    '"' + "gemini-1.5-pro" + '"',
)

# A single banned model for synthetic file creation (split).
_BANNED_MODEL: str = '"gpt-' + '4"'

# Boundary annotation regex (case-insensitive, like the checker).
_BOUNDARY_ANNO_RE: re.Pattern[str] = re.compile(r"#\s*[Bb]oundary:")

# Boundary directories scanned by boundary mode.
_BOUNDARY_DIRS: tuple[Path, ...] = (
    _REPO_ROOT / "tests" / "integration",
    _REPO_ROOT / "tests" / "security",
    _REPO_ROOT / "tests" / "e2e",
)


# ── Helpers ─────────────────────────────────────────────────────────────────


def _load_exclude_files() -> set[str]:
    """Parse EXCLUDE_FILES basenames from the checker script.

    Uses line-by-line parsing to handle ``)`` characters inside comments
    within the EXCLUDE_FILES array.

    Returns:
        Set of filenames excluded from scanning by the checker.
    """
    content = _CHECKER_SCRIPT.read_text()
    lines = content.splitlines()
    in_exclude = False
    result: set[str] = set()
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("EXCLUDE_FILES=("):
            in_exclude = True
            continue
        if in_exclude:
            if stripped == ")":
                break
            result.update(re.findall(r'"([^"]+)"', line))
    return result


def _has_banned_pattern(content: str) -> bool:
    """Check if content contains any banned model name pattern.

    Args:
        content: File content to check.

    Returns:
        True if any banned pattern is found.
    """
    return any(p in content for p in _BANNED_MODEL_PATTERNS)


def _find_files_with_banned_patterns() -> list[Path]:
    """Find .py files in boundary dirs that contain banned patterns.

    Returns:
        List of file paths containing banned model name patterns.
    """
    result: list[Path] = []
    for directory in _BOUNDARY_DIRS:
        if not directory.is_dir():
            continue
        for py_file in sorted(directory.rglob("*.py")):
            if "__pycache__" in py_file.parts:
                continue
            content = py_file.read_text()
            if _has_banned_pattern(content):
                result.append(py_file)
    return result


def _load_precommit_config() -> dict[str, Any]:
    """Parse ``.pre-commit-config.yaml`` and return as dict.

    Returns:
        Parsed YAML config as a dictionary.
    """
    with open(_REPO_ROOT / ".pre-commit-config.yaml") as f:
        data = yaml.safe_load(f)
    assert isinstance(data, dict)
    return cast("dict[str, Any]", data)


def _find_local_hook(hook_id: str) -> dict[str, Any] | None:
    """Find a hook by ID under the ``local`` repo.

    Args:
        hook_id: Hook ID to search for.

    Returns:
        Hook dict or None if not found.
    """
    config = _load_precommit_config()
    repos = cast("list[dict[str, Any]]", config.get("repos", []))
    for repo in repos:
        if repo.get("repo") == "local":
            hooks = cast("list[dict[str, Any]]", repo.get("hooks", []))
            for hook in hooks:
                if hook.get("id") == hook_id:
                    return hook
    return None


def _load_ci_workflow() -> dict[str, Any]:
    """Parse ``.github/workflows/quality.yml`` and return as dict.

    Returns:
        Parsed YAML workflow as a dictionary.
    """
    with open(_REPO_ROOT / ".github" / "workflows" / "quality.yml") as f:
        data = yaml.safe_load(f)
    assert isinstance(data, dict)
    return cast("dict[str, Any]", data)


def _get_gatekeeper_steps() -> list[dict[str, Any]]:
    """Get the steps list from the gatekeeper CI job.

    Returns:
        List of step dictionaries from the gatekeeper job.
    """
    workflow = _load_ci_workflow()
    jobs = cast("dict[str, Any]", workflow.get("jobs", {}))
    gatekeeper = cast("dict[str, Any]", jobs.get("gatekeeper", {}))
    steps = cast("list[dict[str, Any]]", gatekeeper.get("steps", []))
    return steps


def _make_temp_py(directory: Path, content: str) -> str:
    """Create a temp ``.py`` file with *content* in *directory*.

    Uses a ``_gate_synth_`` prefix to avoid being deleted by the
    ``_cleanup_stale_temp_files`` session fixture in ``conftest.py``.

    Args:
        directory: Target scan directory for the temp file.
        content: String content to write to the file.

    Returns:
        Absolute path to the created temp file.  Caller is responsible
        for cleanup via ``Path(path).unlink(missing_ok=True)``.
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
        timeout=60,
    )


# ── S25: Boundary mode passes on clean codebase ────────────────────────────


def test_boundary_mode_passes_on_clean_codebase(
    checker_result: Callable[..., CheckerResult],
) -> None:
    """S25: Verify boundary mode exits 0 on the clean codebase.

    Uses the ``checker_result`` fixture to get cached results for
    ``boundary`` mode and asserts a zero exit code.

    Args:
        checker_result: Fixture providing cached checker results.
    """
    result = checker_result("boundary")
    assert result.returncode == 0, (
        f"Boundary checker failed with exit {result.returncode}\n"
        f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    )


# ── S26: Boundary files with banned patterns have annotations ──────────────

_BOUNDARY_FILES_WITH_PATTERNS: list[Path] = _find_files_with_banned_patterns()


@pytest.mark.parametrize("filepath", _BOUNDARY_FILES_WITH_PATTERNS)
def test_boundary_files_have_annotations(filepath: Path) -> None:
    """S26: Verify files with banned patterns have ``# boundary:`` annotations.

    For each boundary test file containing a banned model name pattern,
    verifies that the file is either excluded from the checker (listed
    in ``EXCLUDE_FILES``) or contains a ``# boundary:`` annotation.

    Args:
        filepath: Path to a boundary test file with banned patterns.
    """
    exclude = _load_exclude_files()
    content = filepath.read_text()

    # Excluded files don't need annotations
    if filepath.name in exclude:
        return

    # Non-excluded files with banned patterns must have annotations
    assert _BOUNDARY_ANNO_RE.search(content), (
        f"{filepath.name} contains banned patterns but has no "
        f"# boundary: annotation"
    )


# ── S27: Removing annotation triggers violation ────────────────────────────


def test_removing_annotation_triggers_violation() -> None:
    """S27: Verify removing ``# boundary:`` annotation triggers a violation.

    Creates a temp file with a banned model name and ``# boundary:``
    annotation, verifies the checker passes, then removes the annotation
    and verifies the checker detects the violation.
    """
    integration_dir = _REPO_ROOT / "tests" / "integration"

    # Clean up stale _gate_synth_ files from crashed sessions
    for stale in integration_dir.glob("_gate_synth_*.py"):
        stale.unlink(missing_ok=True)

    # Content with annotation — checker should pass
    content_with_anno = (
        '"""Synthetic boundary test fixture."""\n'
        f"{_BOUNDARY_ANNO} synthetic test fixture\n"
        f"MODEL = {_BANNED_MODEL}\n"
    )
    # Content without annotation — checker should flag
    content_without_anno = (
        '"""Synthetic boundary test fixture."""\n' f"MODEL = {_BANNED_MODEL}\n"
    )

    tmp_path_str = _make_temp_py(integration_dir, content_with_anno)
    try:
        # Step 1: Verify checker passes with annotation
        result = _run_checker("boundary")
        assert result.returncode == 0, (
            f"Checker should pass with annotation, got exit "
            f"{result.returncode}\nSTDOUT:\n{result.stdout}"
        )

        # Step 2: Remove annotation
        Path(tmp_path_str).write_text(content_without_anno)

        # Step 3: Verify checker detects violation
        result = _run_checker("boundary")
        assert result.returncode != 0, (
            f"Checker should fail without annotation, got exit "
            f"{result.returncode}\nSTDOUT:\n{result.stdout}"
        )
        assert _BOUNDARY_VIOLATION in result.stdout, (
            f"Expected {_BOUNDARY_VIOLATION!r} in stdout, got:\n" f"{result.stdout}"
        )
        assert Path(tmp_path_str).name in result.stdout, (
            f"Expected temp file name in violation output, got:\n" f"{result.stdout}"
        )
    finally:
        Path(tmp_path_str).unlink(missing_ok=True)


# ── S28-S31: Pre-commit config ──────────────────────────────────────────────


def test_precommit_hook_exists() -> None:
    """S28: Verify ``ban-test-hardcodes`` hook exists under ``local`` repo.

    Parses ``.pre-commit-config.yaml`` via ``yaml.safe_load()`` and
    confirms a hook with ``id: ban-test-hardcodes`` exists under the
    ``local`` repo.
    """
    hook = _find_local_hook("ban-test-hardcodes")
    assert hook is not None, (
        "Hook 'ban-test-hardcodes' not found under 'local' repo in "
        f"{_REPO_ROOT / '.pre-commit-config.yaml'}"
    )


def test_precommit_hook_entry_correct() -> None:
    """S29: Verify hook entry is ``bash scripts/check-test-hardcodes.sh``.

    Parses ``.pre-commit-config.yaml`` and confirms the
    ``ban-test-hardcodes`` hook has the correct ``entry`` field.
    """
    hook = _find_local_hook("ban-test-hardcodes")
    assert hook is not None, "ban-test-hardcodes hook not found"
    entry = hook.get("entry")
    assert entry == "bash scripts/check-test-hardcodes.sh", (
        f"Expected entry='bash scripts/check-test-hardcodes.sh', "
        f"got entry={entry!r}"
    )


def test_precommit_hook_files_pattern() -> None:
    """S30: Verify hook ``files`` pattern is ``^tests/``.

    Parses ``.pre-commit-config.yaml`` and confirms the
    ``ban-test-hardcodes`` hook has the correct ``files`` pattern.
    """
    hook = _find_local_hook("ban-test-hardcodes")
    assert hook is not None, "ban-test-hardcodes hook not found"
    files = hook.get("files")
    assert files == "^tests/", f"Expected files='^tests/', got files={files!r}"


def test_precommit_hook_pass_filenames_false() -> None:
    """S31: Verify hook has ``pass_filenames: false``.

    Parses ``.pre-commit-config.yaml`` and confirms the
    ``ban-test-hardcodes`` hook does not pass filenames to the entry
    command.
    """
    hook = _find_local_hook("ban-test-hardcodes")
    assert hook is not None, "ban-test-hardcodes hook not found"
    pass_filenames = hook.get("pass_filenames")
    assert pass_filenames is False, (
        f"Expected pass_filenames=False, got " f"pass_filenames={pass_filenames!r}"
    )


# ── S32-S34: CI workflow ────────────────────────────────────────────────────


def test_ci_has_gatekeeper_job() -> None:
    """S32: Verify ``gatekeeper`` job exists in CI workflow.

    Parses ``.github/workflows/quality.yml`` via ``yaml.safe_load()``
    and confirms the ``gatekeeper`` job exists in the ``jobs`` mapping.
    """
    workflow = _load_ci_workflow()
    jobs = cast("dict[str, Any]", workflow.get("jobs", {}))
    assert (
        "gatekeeper" in jobs
    ), f"gatekeeper job not found in workflow jobs: {list(jobs.keys())}"


def test_ci_gatekeeper_runs_checker_script() -> None:
    """S33: Verify gatekeeper job runs ``check-test-hardcodes.sh``.

    Parses ``.github/workflows/quality.yml`` and confirms the
    ``gatekeeper`` job has a step whose ``run`` command contains
    ``check-test-hardcodes.sh``.
    """
    steps = _get_gatekeeper_steps()
    found = False
    for step in steps:
        run_cmd = step.get("run", "")
        if isinstance(run_cmd, str) and "check-test-hardcodes.sh" in run_cmd:
            found = True
            break
    assert found, (
        "No step in gatekeeper job runs check-test-hardcodes.sh\n"
        f"Steps: {[s.get('run', '') for s in steps]}"
    )


def test_ci_gatekeeper_runs_g5_tests() -> None:
    """S34: Verify gatekeeper job has G5 pytest inversion command.

    Parses ``.github/workflows/quality.yml`` and confirms the
    ``gatekeeper`` job has a step whose ``run`` command contains the
    G5 pytest inversion (``--ignore=tests/unit`` etc.).
    """
    steps = _get_gatekeeper_steps()
    found = False
    for step in steps:
        run_cmd = step.get("run", "")
        if isinstance(run_cmd, str) and "--ignore=tests/unit" in run_cmd:
            found = True
            break
    assert found, (
        "No step in gatekeeper job has G5 pytest inversion command\n"
        f"Steps: {[s.get('run', '') for s in steps]}"
    )
