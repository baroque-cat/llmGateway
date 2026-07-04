"""Tests verifying TESTING*.md documentation completeness and consistency.

These are G5 gatekeeper (structural) tests that ensure the testing
documentation accurately describes the infrastructure it documents.
Scenario references: S23, S24, S25, S26.
"""

from pathlib import Path

_REPO_ROOT: Path = Path(__file__).resolve().parent.parent


def _read_doc(filename: str) -> str:
    """Read a testing documentation file from the repository root.

    Args:
        filename: Name of the markdown file (e.g. ``"TESTING.md"``).

    Returns:
        The full text content of the file.
    """
    return (_REPO_ROOT / filename).read_text(encoding="utf-8")


class TestTestingDocs:
    """Structural tests for the TESTING*.md documentation suite."""

    def test_testing_md_serves_as_documentation_index(self) -> None:
        """Verify TESTING.md links to all sibling docs and has quick-start.

        Scenario S23: TESTING.md serves as the documentation index with
        links to GUIDE/RUN/GATEKEEPER, quick-start commands, directory
        structure, and role-based sections.
        """
        content = _read_doc("TESTING.md")

        # Links to all 3 sibling docs
        assert "TESTING-GUIDE.md" in content
        assert "TESTING-RUN.md" in content
        assert "TESTING-GATEKEEPER.md" in content

        # Quick-start command
        assert "make test" in content or "pytest" in content

        # Directory structure tree (code block with tests/ or src/)
        assert "tests/" in content

        # Role-based sections
        lower = content.lower()
        assert "writing a test" in lower
        assert "running tests" in lower
        assert "maintaining the gatekeeper" in lower

    def test_testing_guide_documents_golden_rule(self) -> None:
        """Verify TESTING-GUIDE.md documents the Golden Rule and CanonicalConfig.

        Scenario S24: TESTING-GUIDE.md documents the zero-hardcodes Golden
        Rule, CanonicalConfig usage, test-safe overrides, autouse fixture,
        boundary annotations, anti-patterns, and compliance checklist.
        """
        content = _read_doc("TESTING-GUIDE.md")
        lower = content.lower()

        # Golden Rule (zero hardcodes)
        assert "golden rule" in lower

        # CanonicalConfig and how to use it
        assert "canonicalconfig" in lower
        assert "how to use" in lower

        # Test-safe overrides concept
        assert "test-safe" in lower
        assert "override" in lower

        # Autouse fixture
        assert "_set_config_vars_from_canonical" in content

        # Boundary annotations section
        assert "# boundary:" in content
        assert "boundary annotation" in lower

        # Anti-patterns section (at least 2 documented)
        assert "anti-pattern" in lower
        antipattern_topics: list[str] = [
            "_base_env",
            "os.environ",
            "model name",
            "provider type",
        ]
        found_antipatterns = sum(1 for t in antipattern_topics if t in lower)
        assert found_antipatterns >= 2

        # Compliance checklist
        assert "compliance checklist" in lower

    def test_testing_run_documents_makefile_targets(self) -> None:
        """Verify TESTING-RUN.md documents Makefile targets and isolation groups.

        Scenario S25: TESTING-RUN.md documents Makefile targets, all 6
        process-isolation groups (G1-G6), the dash-prefix convention,
        markers, timeout policy, and typical workflow.
        """
        content = _read_doc("TESTING-RUN.md")
        lower = content.lower()

        # Makefile targets table
        assert "makefile" in lower
        assert "make test" in content

        # All 6 isolation groups
        for group in ("G1", "G2", "G3", "G4", "G5", "G6"):
            assert group in content

        # Dash-prefix convention (fault-tolerant vs gate)
        assert "fault-tolerant" in lower
        assert "gate" in lower

        # Markers
        assert "slow" in lower
        assert "postgres" in lower
        assert "meta" in lower

        # Timeout policy
        assert "timeout" in lower

        # Typical workflow
        assert "typical workflow" in lower

    def test_testing_gatekeeper_documents_infrastructure(self) -> None:
        """Verify TESTING-GATEKEEPER.md documents the gatekeeper infrastructure.

        Scenario S26: TESTING-GATEKEEPER.md documents all 4 script modes,
        banned-pattern arrays, boundary lookback algorithm, cache fixtures
        chain, 3-tier test classification, and usage examples.
        """
        content = _read_doc("TESTING-GATEKEEPER.md")
        lower = content.lower()

        # 4 modes: canonical, boundary, root, all
        assert "canonical" in lower
        assert "boundary" in lower
        assert "root" in lower
        assert "all modes" in lower

        # Banned-pattern arrays
        assert "BANNED_PROD_URLS" in content
        assert "BANNED_SECRETS" in content
        assert "BANNED_DB_PARAMS" in content

        # Boundary lookback algorithm
        assert "lookback" in lower

        # Cache fixtures chain (3 layers)
        assert "_cached_checker_results" in content
        assert "checker_result" in content
        assert "CheckerResult" in content

        # 3-tier test classification
        assert "clean-codebase" in lower
        assert "synthetic violation" in lower
        assert "consistency" in lower

        # Usage examples (bash commands)
        assert "check-test-hardcodes.sh" in content
        assert "bash" in lower
