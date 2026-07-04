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
    "test_conftest_checker_cache.py",
    "test_project_structure.py",
    "test_makefile_groups.py",
    "test_canonical_integrity.py",
    "test_secret_isolation.py",
    "test_env_example.py",
    "test_documentation_sync.py",
    "test_testing_docs.py",
    "test_hardcode_checker_core.py",
    "test_hardcode_checker_production_urls.py",
    "test_boundary_compliance.py",
    "test_hardcode_checker_regression.py",
    "test_docker_test_db.py",
    "test_security.py",
    "test_ci_pipeline.py",
    "test_layer_import_scan.py",
    "test_pre_commit_config.py",
    "test_metrics_fixture_dedup.py",
    "test_postgres_runner.py",
    "test_test_infra_polish.py",
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

    def test_banned_regex_database_config_password(self) -> None:
        """Verify BANNED_OTHER_PCRE contains a DatabaseConfig password pattern.

        Reads the script source and checks that the ``BANNED_OTHER_PCRE`` array
        contains a PCRE regex pattern for detecting non-canonical
        ``DatabaseConfig(...password=...)`` constructor calls. The pattern uses
        a negative lookahead ``(?!test_password)`` to permit the canonical value
        ``test_password`` while flagging any other password as a violation.
        """
        script = _CHECKER_SCRIPT.read_text()

        # Extract the BANNED_OTHER_PCRE section
        section_start: int = script.index("BANNED_OTHER_PCRE=(")
        section_end: int = script.index("\n)", section_start)
        section: str = script[section_start:section_end]

        # Verify DatabaseConfig pattern is present in the section
        assert (
            "DatabaseConfig" in section
        ), "DatabaseConfig pattern not found in BANNED_OTHER_PCRE"

        # Verify the pattern uses negative lookahead for the canonical password
        assert (
            "(?!test_password" in section
        ), "Negative lookahead for test_password not found in BANNED_OTHER_PCRE"

        # Verify password= keyword is part of the pattern
        assert (
            "password=" in section
        ), "password= keyword not found in BANNED_OTHER_PCRE"

    def test_banned_regex_httpcore_version(self) -> None:
        """Verify BANNED_OTHER_REGEX contains an httpcore version pattern.

        Reads the script source and checks that the ``BANNED_OTHER_REGEX`` array
        contains a regex pattern for detecting non-canonical httpcore versions.
        The pattern enforces the canonical version ``1.0.9`` by matching
        versions where the major, minor, or patch components differ from 1, 0,
        and 9 respectively.
        """
        script = _CHECKER_SCRIPT.read_text()

        # Extract the BANNED_OTHER_REGEX section
        section_start: int = script.index("BANNED_OTHER_REGEX=(")
        section_end: int = script.index("\n)", section_start)
        section: str = script[section_start:section_end]

        # Verify httpcore pattern is present in the section
        assert "httpcore" in section, "httpcore pattern not found in BANNED_OTHER_REGEX"

        # Verify the pattern enforces canonical version 1.0.9
        assert "version" in section, "version keyword not found in BANNED_OTHER_REGEX"
        assert (
            "[^1]" in section
        ), "Major version enforcement [^1] not found in BANNED_OTHER_REGEX"
        assert (
            "[^0]" in section
        ), "Minor version enforcement [^0] not found in BANNED_OTHER_REGEX"
        assert (
            "[^9]" in section
        ), "Patch version enforcement [^9] not found in BANNED_OTHER_REGEX"

    def test_exclude_files_contains_test_postgres_policy(self) -> None:
        """Verify EXCLUDE_FILES contains test_postgres_policy.py.

        Reads the script source and checks that ``"test_postgres_policy.py"``
        is present in the ``EXCLUDE_FILES`` array, ensuring the upcoming
        postgres policy gatekeeper test is excluded from all pattern checks.
        """
        script = _CHECKER_SCRIPT.read_text()

        # Extract the EXCLUDE_FILES section
        section_start: int = script.index("EXCLUDE_FILES=(")
        section_end: int = script.index("\n)", section_start)
        section: str = script[section_start:section_end]

        # Verify test_postgres_runner.py is excluded from scanning
        assert (
            '"test_postgres_runner.py"' in section
        ), "test_postgres_runner.py not found in EXCLUDE_FILES"
