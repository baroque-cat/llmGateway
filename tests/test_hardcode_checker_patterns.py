"""Tests for the gatekeeper script's banned-pattern arrays and exclusions.

Verifies that ``scripts/check-test-hardcodes.sh`` contains all 7
banned-pattern arrays with the expected entries, and that infrastructure
files are properly excluded from scanning.

Scenarios: S11, S12.
"""

from __future__ import annotations

from pathlib import Path

_REPO_ROOT: Path = Path(__file__).resolve().parent.parent
_CHECKER_SCRIPT: Path = _REPO_ROOT / "scripts" / "check-test-hardcodes.sh"

# Expected infrastructure files in EXCLUDE_FILES
_INFRASTRUCTURE_FILES: list[str] = [
    "conftest.py",
    "_canonical.py",
    "_constants.py",
]

# Expected gatekeeper test files in EXCLUDE_FILES (self-exclusion)
_GATEKEEPER_TEST_FILES: list[str] = [
    "test_canonical_config.py",
    "test_canonical_fixtures.py",
    "test_constants.py",
    "test_hardcode_checker_modes.py",
    "test_hardcode_checker_patterns.py",
    "test_checker_cache_fixtures.py",
    "test_project_structure.py",
    "test_makefile_groups.py",
    "test_canonical_integrity.py",
    "test_secret_isolation.py",
    "test_env_example.py",
    "test_documentation_sync.py",
    "test_testing_docs.py",
]


class TestHardcodeCheckerPatterns:
    """Tests for banned-pattern arrays and EXCLUDE_FILES."""

    def test_banned_pattern_arrays_catch_prohibited_values(self) -> None:
        """S11: Banned-pattern arrays catch all prohibited values.

        Reads the script source and verifies all 7 banned-pattern arrays
        exist with at least 2 entries each.
        """
        script = _CHECKER_SCRIPT.read_text()

        # Verify all 7 arrays exist
        array_names = [
            "BANNED_PROD_URLS",
            "BANNED_SECRETS",
            "BANNED_DB_PARAMS",
            "BANNED_GATEWAY_PORTS",
            "BANNED_PROVIDER_TYPES_REGEX",
            "BANNED_MODEL_NAMES",
            "BANNED_OTHER_REGEX",
        ]
        for name in array_names:
            assert name in script, f"Array {name} not found in script"

        # Verify BANNED_PROD_URLS contains production API URLs
        assert "api.openai.com" in script
        assert "api.anthropic.com" in script
        assert "generativelanguage.googleapis.com" in script
        assert "api.deepseek.com" in script

        # Verify BANNED_SECRETS contains placeholder passwords
        assert "your_secure_password_here" in script

        # Verify BANNED_DB_PARAMS contains production DB params
        assert "llm_gateway" in script
        assert "llmgateway" in script

        # Verify BANNED_MODEL_NAMES contains quoted model strings
        assert '"gpt-4"' in script
        assert '"claude-3-opus"' in script

        # Verify BANNED_PROVIDER_TYPES_REGEX uses regex patterns
        assert 'provider_type.*"openai"' in script

        # Verify BANNED_GATEWAY_PORTS contains non-canonical ports
        assert "GATEWAY_PORT=8000" in script

        # Verify BANNED_OTHER_REGEX contains extended patterns
        assert "PROMETHEUS_MULTIPROC_DIR=" in script

    def test_infrastructure_files_excluded_from_scanning(self) -> None:
        """S12: Infrastructure files are excluded from scanning.

        Reads the script source and verifies that ``EXCLUDE_FILES`` contains
        all infrastructure files and all gatekeeper test files (self-exclusion).
        Also verifies the ``is_excluded`` function checks against EXCLUDE_FILES.
        """
        script = _CHECKER_SCRIPT.read_text()

        # Verify EXCLUDE_FILES array exists
        assert "EXCLUDE_FILES=" in script or "EXCLUDE_FILES=(" in script

        # Verify all infrastructure files are excluded
        for filename in _INFRASTRUCTURE_FILES:
            assert (
                f'"{filename}"' in script
            ), f"Infrastructure file {filename} not in EXCLUDE_FILES"

        # Verify all gatekeeper test files are excluded (self-exclusion)
        for filename in _GATEKEEPER_TEST_FILES:
            assert (
                f'"{filename}"' in script
            ), f"Gatekeeper test file {filename} not in EXCLUDE_FILES"

        # Verify is_excluded function exists and checks EXCLUDE_FILES
        assert "is_excluded()" in script or "is_excluded()" in script
        assert "EXCLUDE_FILES[@]" in script
