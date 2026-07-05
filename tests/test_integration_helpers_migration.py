"""Gatekeeper test: integration helpers migration.

Verifies that the ``inject_helpers`` fixture has been removed from
``tests/integration/conftest.py`` and that no F821 (undefined-name)
ruff violations remain for ``make_mock_request`` or
``create_mock_provider_config``.

Spec scenario: No F821 errors after removal (S10).
"""

import subprocess
from pathlib import Path

CONFTEST_PATH = Path(__file__).parent / "integration" / "conftest.py"
PROJECT_ROOT = Path(__file__).parent.parent


def test_no_f821_errors_for_helper_names() -> None:
    """S10: ruff check reports zero F821 violations for helper names.

    After removing ``inject_helpers`` and adding explicit imports to all
    consuming test files, ``ruff check --select F821`` must report zero
    violations related to ``make_mock_request`` or
    ``create_mock_provider_config``.
    """
    result = subprocess.run(
        [
            "poetry",
            "run",
            "ruff",
            "check",
            "tests/",
            "--select",
            "F821",
            "--output-format=concise",
        ],
        capture_output=True,
        text=True,
        cwd=PROJECT_ROOT,
    )
    f821_lines = [
        line
        for line in result.stdout.splitlines()
        if "F821" in line
        and ("make_mock_request" in line or "create_mock_provider_config" in line)
    ]
    assert (
        len(f821_lines) == 0
    ), "Found F821 violations for helper names:\n" + "\n".join(f821_lines)


def test_inject_helpers_fixture_removed() -> None:
    """The ``inject_helpers`` fixture must not exist in conftest.py.

    After migration to explicit imports, the runtime namespace-injection
    fixture must be fully removed from ``tests/integration/conftest.py``.
    """
    content = CONFTEST_PATH.read_text()
    assert (
        "inject_helpers" not in content
    ), "inject_helpers fixture must be removed from tests/integration/conftest.py"
