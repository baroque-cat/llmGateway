"""Structural test verifying Makefile test-group configuration (Scenario S18).

Ensures that the Makefile defines 6 process-isolation test groups (G1-G6)
with correct prefix conventions and collection patterns.
"""

from pathlib import Path

_REPO_ROOT: Path = Path(__file__).resolve().parent.parent


def test_makefile_groups_validates_structure() -> None:
    """Verify Makefile has 6 test groups with correct prefixes and patterns.

    Checks:
        - G1: no ``-`` prefix (gate -- failure stops the build)
        - G2-G5: ``-`` prefix (fault-tolerant)
        - G5: uses inversion pattern (multiple ``--ignore=`` flags)
        - G1: excludes ``tests/unit/config/`` (config tests are in G2)
        - G6: uses ``-m slow`` marker filter
    """
    makefile_text = (_REPO_ROOT / "Makefile").read_text(encoding="utf-8")
    lines: list[str] = makefile_text.splitlines()
    pytest_lines: list[str] = [
        line.strip() for line in lines if "poetry run pytest" in line
    ]

    # --- G1: unit tests (gate -- no '-' prefix) ---
    g1_line: str | None = next(
        (
            line
            for line in pytest_lines
            if "tests/unit/ --ignore=tests/unit/config" in line
        ),
        None,
    )
    assert g1_line is not None, "G1 pytest line not found in Makefile"
    assert not g1_line.startswith("-"), "G1 should NOT have '-' prefix (gate)"
    assert (
        "--ignore=tests/unit/config" in g1_line
    ), "G1 should exclude tests/unit/config/ (config tests are in G2)"

    # --- G2: config tests (fault-tolerant -- has '-' prefix) ---
    g2_line: str | None = next(
        (line for line in pytest_lines if "tests/unit/config/" in line),
        None,
    )
    assert g2_line is not None, "G2 pytest line not found in Makefile"
    assert g2_line.startswith("-"), "G2 should have '-' prefix (fault-tolerant)"

    # --- G3: integration + security + e2e (fault-tolerant) ---
    g3_line: str | None = next(
        (line for line in pytest_lines if "tests/integration/" in line),
        None,
    )
    assert g3_line is not None, "G3 pytest line not found in Makefile"
    assert g3_line.startswith("-"), "G3 should have '-' prefix (fault-tolerant)"

    # --- G4: batching tests (fault-tolerant) ---
    g4_line: str | None = next(
        (line for line in pytest_lines if "tests/batching/" in line),
        None,
    )
    assert g4_line is not None, "G4 pytest line not found in Makefile"
    assert g4_line.startswith("-"), "G4 should have '-' prefix (fault-tolerant)"

    # --- G5: root-level tests (fault-tolerant, inversion pattern) ---
    g5_line: str | None = next(
        (
            line
            for line in pytest_lines
            if "--ignore=tests/unit --ignore=tests/integration" in line
        ),
        None,
    )
    assert g5_line is not None, "G5 pytest line not found in Makefile"
    assert g5_line.startswith("-"), "G5 should have '-' prefix (fault-tolerant)"
    ignore_count: int = g5_line.count("--ignore=")
    assert ignore_count >= 3, (
        f"G5 should use inversion pattern (>=3 --ignore= flags), "
        f"found {ignore_count}"
    )

    # --- G6: stress tests (marker filter) ---
    g6_line: str | None = next(
        (line for line in pytest_lines if "tests/stress/" in line),
        None,
    )
    assert g6_line is not None, "G6 pytest line not found in Makefile"
    assert "-m slow" in g6_line, "G6 should use '-m slow' marker filter"
