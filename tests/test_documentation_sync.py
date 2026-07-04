"""Structural test verifying testing documentation sync (Scenario S22).

Ensures that all 4 TESTING*.md files exist at the repo root and contain
expected content references, and that ``tests/AGENTS.md`` references
CanonicalConfig.
"""

from pathlib import Path

_REPO_ROOT: Path = Path(__file__).resolve().parent.parent

_TESTING_DOCS: list[Path] = [
    _REPO_ROOT / "TESTING.md",
    _REPO_ROOT / "TESTING-GUIDE.md",
    _REPO_ROOT / "TESTING-RUN.md",
    _REPO_ROOT / "TESTING-GATEKEEPER.md",
]


def test_documentation_sync_verifies_testing_docs() -> None:
    """Verify TESTING docs exist and contain expected content (S22).

    Checks:
        - All 4 TESTING*.md files exist at repo root
        - ``TESTING.md`` references the other 3 docs
        - ``TESTING-GUIDE.md`` mentions Golden Rule / CanonicalConfig
        - ``TESTING-RUN.md`` mentions Makefile and G1-G6
        - ``TESTING-GATEKEEPER.md`` mentions all 4 modes
        - ``tests/AGENTS.md`` references CanonicalConfig
    """
    # --- All 4 TESTING docs exist ---
    for doc_path in _TESTING_DOCS:
        assert doc_path.is_file(), f"Missing testing doc: {doc_path}"

    # --- TESTING.md references other 3 docs ---
    testing_md = (_REPO_ROOT / "TESTING.md").read_text(encoding="utf-8")
    assert (
        "TESTING-GUIDE.md" in testing_md
    ), "TESTING.md should reference TESTING-GUIDE.md"
    assert "TESTING-RUN.md" in testing_md, "TESTING.md should reference TESTING-RUN.md"
    assert (
        "TESTING-GATEKEEPER.md" in testing_md
    ), "TESTING.md should reference TESTING-GATEKEEPER.md"

    # --- TESTING-GUIDE.md mentions Golden Rule / CanonicalConfig ---
    guide_md = (_REPO_ROOT / "TESTING-GUIDE.md").read_text(encoding="utf-8")
    assert (
        "Golden Rule" in guide_md or "CanonicalConfig" in guide_md
    ), "TESTING-GUIDE.md should mention Golden Rule or CanonicalConfig"

    # --- TESTING-RUN.md mentions Makefile and G1-G6 ---
    run_md = (_REPO_ROOT / "TESTING-RUN.md").read_text(encoding="utf-8")
    assert "Makefile" in run_md, "TESTING-RUN.md should mention Makefile"
    for group in ("G1", "G2", "G3", "G4", "G5", "G6"):
        assert group in run_md, f"TESTING-RUN.md should mention {group}"

    # --- TESTING-GATEKEEPER.md mentions all 4 modes ---
    gatekeeper_md = (_REPO_ROOT / "TESTING-GATEKEEPER.md").read_text(encoding="utf-8")
    for mode in ("canonical", "boundary", "root", "all"):
        assert (
            mode in gatekeeper_md
        ), f"TESTING-GATEKEEPER.md should mention mode '{mode}'"

    # --- tests/AGENTS.md references CanonicalConfig ---
    agents_md = (_REPO_ROOT / "tests" / "AGENTS.md").read_text(encoding="utf-8")
    assert (
        "CanonicalConfig" in agents_md
    ), "tests/AGENTS.md should reference CanonicalConfig"
