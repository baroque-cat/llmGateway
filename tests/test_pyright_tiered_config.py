#!/usr/bin/env python3
"""Tests verifying the tiered pyright strictness configuration.

Covers spec scenarios #1-#9 from the ``pyright-tiered-strictness`` capability:

    #1-#3: Strict mode reports type errors in ``src/core/``.
    #4-#8: Basic mode catches real errors but suppresses noise in
           ``src/services/`` and ``tests/``.
    #9:    ``pyrightconfig.json`` has the correct tiered format.

A module-scoped fixture creates a synthetic temp project mimicking the
project's tiered config (basic globally, strict for ``src/core`` and
``src/config``), runs pyright once via subprocess, and caches the parsed
diagnostics. All behavior test functions share this single run to avoid
repeated pyright invocations (~5 s each).
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any, cast

import pytest

_REPO_ROOT: Path = Path(__file__).resolve().parent.parent

# Synthetic pyrightconfig.json for the temp project (mimics actual tiered config).
_SYNTHETIC_CONFIG: str = """\
{
  "include": ["src", "tests"],
  "typeCheckingMode": "basic",
  "strict": ["src/core", "src/config"],
  "pythonVersion": "3.13"
}
"""

# Synthetic file in src/core/ with deliberate type issues (strict mode).
_SYNTHETIC_CORE_FILE: str = """\
def _accept_int(x: int) -> None:
    _ = x


def trigger_type_mismatch() -> None:
    _accept_int("wrong")


def trigger_unknown_member() -> None:
    x: int = 1
    _ = x.foo


class _HasSecret:
    _secret: int = 1


def trigger_private_usage() -> None:
    obj = _HasSecret()
    _ = obj._secret
"""

# Synthetic file in src/services/ with deliberate type issues (basic mode).
_SYNTHETIC_SERVICES_FILE: str = """\
def _accept_int(x: int) -> None:
    _ = x


def trigger_argument_type_mismatch() -> None:
    _accept_int("wrong")


def trigger_undefined_variable() -> None:
    print(undefined_name)
"""

# Synthetic file in tests/ with issues that basic mode should suppress.
_SYNTHETIC_TESTS_FILE: str = """\
from unittest.mock import MagicMock


class _HasPrivate:
    _secret: int = 1


def test_magicmock_unknown_member() -> None:
    mock = MagicMock()
    mock.some_attribute.do_thing()


def test_untyped_fixture_params(tmp_path):
    _ = tmp_path


def test_private_usage_in_tests() -> None:
    obj = _HasPrivate()
    _ = obj._secret
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_pyrightconfig() -> dict[str, Any]:
    """Parse the actual ``pyrightconfig.json`` at repo root.

    Returns:
        Parsed configuration as a dictionary.

    Raises:
        AssertionError: If the parsed JSON is not a dict.
    """
    config_path = _REPO_ROOT / "pyrightconfig.json"
    data: Any = json.loads(config_path.read_text(encoding="utf-8"))
    assert isinstance(data, dict), "pyrightconfig.json did not parse to a dict"
    return cast("dict[str, Any]", data)


def _filter_diagnostics(
    diagnostics: list[dict[str, Any]],
    rule: str,
    file_substr: str,
) -> list[dict[str, Any]]:
    """Filter pyright diagnostics by rule name and file path substring.

    Args:
        diagnostics: List of pyright ``generalDiagnostics`` dicts.
        rule: Pyright rule name (e.g., ``reportArgumentType``).
        file_substr: Substring to match in the diagnostic's ``file`` path.

    Returns:
        List of matching diagnostic dicts.
    """
    return [
        d
        for d in diagnostics
        if d.get("rule") == rule and file_substr in d.get("file", "")
    ]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def _synthetic_pyright_diagnostics(  # pyright: ignore[reportUnusedFunction]
    tmp_path_factory: pytest.TempPathFactory,
) -> list[dict[str, Any]]:
    """Module-scoped: create temp project, run pyright once, return diagnostics.

    Creates a synthetic temp project mimicking the project's tiered pyright
    config (basic globally, strict for ``src/core`` and ``src/config``). Runs
    pyright once via subprocess and caches the parsed ``generalDiagnostics``
    list. All behavior test functions share this single run to avoid repeated
    pyright invocations.

    Returns:
        List of pyright ``generalDiagnostics`` dicts.

    Raises:
        RuntimeError: If pyright produces no stdout (e.g., crash or misconfig).
    """
    project_dir = tmp_path_factory.mktemp("pyright_tiered")

    # Create directory structure
    (project_dir / "src" / "core").mkdir(parents=True)
    (project_dir / "src" / "services").mkdir(parents=True)
    (project_dir / "tests").mkdir(parents=True)

    # Write pyrightconfig.json and synthetic Python files
    (project_dir / "pyrightconfig.json").write_text(_SYNTHETIC_CONFIG, encoding="utf-8")
    (project_dir / "src" / "core" / "test_synth_strict.py").write_text(
        _SYNTHETIC_CORE_FILE, encoding="utf-8"
    )
    (project_dir / "src" / "services" / "test_synth_basic.py").write_text(
        _SYNTHETIC_SERVICES_FILE, encoding="utf-8"
    )
    (project_dir / "tests" / "test_synth_test.py").write_text(
        _SYNTHETIC_TESTS_FILE, encoding="utf-8"
    )

    # Run pyright on the temp project. cwd=repo root so poetry finds
    # pyproject.toml; --project points pyright at the temp config.
    result = subprocess.run(
        [
            "poetry",
            "run",
            "pyright",
            "--project",
            str(project_dir),
            "--outputjson",
        ],
        capture_output=True,
        text=True,
        timeout=60,
        cwd=str(_REPO_ROOT),
    )

    if not result.stdout:
        raise RuntimeError(
            f"pyright produced no stdout (returncode={result.returncode}). "
            f"stderr: {result.stderr}"
        )

    data: Any = json.loads(result.stdout)
    return cast("list[dict[str, Any]]", data.get("generalDiagnostics", []))


# ===========================================================================
# Class 1: TestPyrightConfigFormat (scenario #9)
# ===========================================================================


@pytest.mark.meta
class TestPyrightConfigFormat:
    """Verify the actual ``pyrightconfig.json`` has the tiered format."""

    def test_pyrightconfig_has_tiered_format(self) -> None:
        """#9: ``pyrightconfig.json`` defines basic mode + strict array.

        Asserts:
            - ``typeCheckingMode`` is ``"basic"``.
            - ``strict`` array contains ``"src/core"`` and ``"src/config"``.
            - ``exclude`` array contains ``"src/core/http2"``.
            - ``include`` array does NOT contain ``"tests"``.
            - ``reportUnnecessaryTypeIgnoreComment`` is ``false``.
        """
        config = _load_pyrightconfig()

        # Global mode is basic
        assert (
            config.get("typeCheckingMode") == "basic"
        ), "typeCheckingMode must be 'basic' (global default)"

        # Strict array promotes src/core and src/config
        strict_dirs = config.get("strict", [])
        assert isinstance(strict_dirs, list)
        assert "src/core" in strict_dirs, "strict array must contain 'src/core'"
        assert "src/config" in strict_dirs, "strict array must contain 'src/config'"

        # Exclude array contains src/core/http2 (temporary backport package)
        exclude_dirs = config.get("exclude", [])
        assert isinstance(exclude_dirs, list)
        assert (
            "src/core/http2" in exclude_dirs
        ), "exclude array must contain 'src/core/http2'"

        # Include array does NOT contain tests (tests excluded from default pyright)
        include_dirs = config.get("include", [])
        assert isinstance(include_dirs, list)
        assert "tests" not in include_dirs, (
            "include array must NOT contain 'tests' "
            "(tests excluded from default runs)"
        )

        # reportUnnecessaryTypeIgnoreComment disabled (stale ignores after switch)
        assert (
            config.get("reportUnnecessaryTypeIgnoreComment") is False
        ), "reportUnnecessaryTypeIgnoreComment must be false"


# ===========================================================================
# Class 2: TestPyrightStrictModeBehavior (scenarios #1-#3)
# ===========================================================================


@pytest.mark.meta
class TestPyrightStrictModeBehavior:
    """Verify strict mode reports type errors in ``src/core/``."""

    def test_strict_mode_reports_type_mismatch_in_core(
        self, _synthetic_pyright_diagnostics: list[dict[str, Any]]
    ) -> None:
        """#1: Strict mode reports ``reportArgumentType`` in ``src/core/``.

        A file in ``src/core/`` passes a ``str`` where ``int`` is expected.
        Pyright in strict mode SHALL report ``reportArgumentType``.
        """
        matching = _filter_diagnostics(
            _synthetic_pyright_diagnostics,
            "reportArgumentType",
            "test_synth_strict",
        )
        assert (
            len(matching) > 0
        ), "Expected reportArgumentType in src/core/ (strict mode)"

    def test_strict_mode_reports_unknown_member_in_core(
        self, _synthetic_pyright_diagnostics: list[dict[str, Any]]
    ) -> None:
        """#2: Strict mode reports ``reportUnknownMemberType`` in ``src/core/``.

        A file in ``src/core/`` accesses a non-existent attribute on a typed
        ``int``. Pyright in strict mode SHALL report
        ``reportUnknownMemberType``.
        """
        matching = _filter_diagnostics(
            _synthetic_pyright_diagnostics,
            "reportUnknownMemberType",
            "test_synth_strict",
        )
        assert (
            len(matching) > 0
        ), "Expected reportUnknownMemberType in src/core/ (strict mode)"

    def test_strict_mode_reports_private_usage_in_core(
        self, _synthetic_pyright_diagnostics: list[dict[str, Any]]
    ) -> None:
        """#3: Strict mode reports ``reportPrivateUsage`` in ``src/core/``.

        A file in ``src/core/`` accesses a ``_``-prefixed private member from
        outside its defining class. Pyright in strict mode SHALL report
        ``reportPrivateUsage``.
        """
        matching = _filter_diagnostics(
            _synthetic_pyright_diagnostics,
            "reportPrivateUsage",
            "test_synth_strict",
        )
        assert (
            len(matching) > 0
        ), "Expected reportPrivateUsage in src/core/ (strict mode)"


# ===========================================================================
# Class 3: TestPyrightBasicModeBehavior (scenarios #4-#8)
# ===========================================================================


@pytest.mark.meta
class TestPyrightBasicModeBehavior:
    """Verify basic mode catches real errors but suppresses noise."""

    def test_basic_mode_catches_argument_type_mismatch(
        self, _synthetic_pyright_diagnostics: list[dict[str, Any]]
    ) -> None:
        """#4: Basic mode catches ``reportArgumentType`` in ``src/services/``.

        A file in ``src/services/`` passes a ``str`` where ``int`` is expected.
        Pyright in basic mode SHALL still report ``reportArgumentType``.
        """
        matching = _filter_diagnostics(
            _synthetic_pyright_diagnostics,
            "reportArgumentType",
            "test_synth_basic",
        )
        assert (
            len(matching) > 0
        ), "Expected reportArgumentType in src/services/ (basic mode catches this)"

    def test_basic_mode_catches_undefined_variable(
        self, _synthetic_pyright_diagnostics: list[dict[str, Any]]
    ) -> None:
        """#5: Basic mode catches ``reportUndefinedVariable`` in ``src/services/``.

        A file in ``src/services/`` references an undefined variable. Pyright
        in basic mode SHALL still report ``reportUndefinedVariable``.
        """
        matching = _filter_diagnostics(
            _synthetic_pyright_diagnostics,
            "reportUndefinedVariable",
            "test_synth_basic",
        )
        assert len(matching) > 0, (
            "Expected reportUndefinedVariable in src/services/ "
            "(basic mode catches this)"
        )

    def test_basic_mode_suppresses_magicmock_unknown_member(
        self, _synthetic_pyright_diagnostics: list[dict[str, Any]]
    ) -> None:
        """#6: Basic mode suppresses ``reportUnknownMemberType`` for MagicMock.

        A file in ``tests/`` accesses attributes on a ``MagicMock`` object.
        Pyright in basic mode SHALL NOT report ``reportUnknownMemberType``.
        """
        matching = _filter_diagnostics(
            _synthetic_pyright_diagnostics,
            "reportUnknownMemberType",
            "test_synth_test",
        )
        assert (
            len(matching) == 0
        ), "reportUnknownMemberType should NOT be reported in tests/ (basic mode)"

    def test_basic_mode_suppresses_untyped_fixture_params(
        self, _synthetic_pyright_diagnostics: list[dict[str, Any]]
    ) -> None:
        """#7: Basic mode suppresses untyped parameter errors in ``tests/``.

        A file in ``tests/`` has a test function with an untyped parameter
        (``tmp_path``). Pyright in basic mode SHALL NOT report
        ``reportMissingParameterType`` or ``reportUnknownParameterType``.
        """
        for rule in (
            "reportMissingParameterType",
            "reportUnknownParameterType",
        ):
            matching = _filter_diagnostics(
                _synthetic_pyright_diagnostics, rule, "test_synth_test"
            )
            assert (
                len(matching) == 0
            ), f"{rule} should NOT be reported in tests/ (basic mode)"

    def test_basic_mode_suppresses_private_usage_in_tests(
        self, _synthetic_pyright_diagnostics: list[dict[str, Any]]
    ) -> None:
        """#8: Basic mode suppresses ``reportPrivateUsage`` in ``tests/``.

        A file in ``tests/`` accesses a ``_``-prefixed private member from
        outside its defining class. Pyright in basic mode SHALL NOT report
        ``reportPrivateUsage``.
        """
        matching = _filter_diagnostics(
            _synthetic_pyright_diagnostics,
            "reportPrivateUsage",
            "test_synth_test",
        )
        assert (
            len(matching) == 0
        ), "reportPrivateUsage should NOT be reported in tests/ (basic mode)"
