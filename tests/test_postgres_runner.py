"""Tests for the PostgreSQL test-runner lifecycle script.

Verifies that ``scripts/run-postgres-tests.sh`` follows the required
container lifecycle: podman-first engine detection, pre-teardown with
error suppression, ``--wait``-based readiness (no ``sleep``), targeting
``test-database`` (not production ``database``), exit-code-5 handling,
post-teardown without error suppression, correct lifecycle ordering, and
v2 compose syntax.  Also verifies the Makefile ``test-postgres`` target
delegates to the script.

Scenarios: engine detection, pre-teardown, fresh start, test groups,
post-teardown, v2 syntax, Makefile delegation.
"""

from __future__ import annotations

from pathlib import Path

_REPO_ROOT: Path = Path(__file__).resolve().parent.parent
_RUNNER_SCRIPT: Path = _REPO_ROOT / "scripts" / "run-postgres-tests.sh"
_MAKEFILE: Path = _REPO_ROOT / "Makefile"


def _line_index(lines: list[str], pattern: str) -> int | None:
    """Return the 0-based index of the first line containing ``pattern``.

    Args:
        lines: Script source split into lines.
        pattern: Substring to search for.

    Returns:
        Index of the first matching line, or ``None`` if not found.
    """
    return next((i for i, line in enumerate(lines) if pattern in line), None)


class TestPostgresRunner:
    """Tests for the postgres test-runner script and Makefile delegation."""

    def test_script_engine_detection_ordered_correctly(self) -> None:
        """Engine detection: docker-first when DOCKER_HOST is set, then podman,
        then docker as fallback, exiting 0 if none available.

        Verifies:
        - ``DOCKER_HOST`` check appears before ``command -v podman``
        - ``command -v podman`` appears before the fallback ``command -v docker``
        - ``exit 0`` skip path exists
        """
        script = _RUNNER_SCRIPT.read_text()

        assert "DOCKER_HOST" in script, "Missing DOCKER_HOST CI detection"
        assert "command -v podman" in script, "Missing podman detection"
        assert "command -v docker" in script, "Missing docker detection"
        assert "exit 0" in script, "Missing exit-0 skip path"

        # Docker-first logic (when DOCKER_HOST is set) must appear before
        # the podman fallback, which must appear before the final docker
        # fallback.
        host_idx = script.index("DOCKER_HOST")
        podman_idx = script.index("command -v podman")
        # Second "command -v docker" is the fallback; find it after podman.
        fallback_docker_idx = script.index("command -v docker", podman_idx)

        assert (
            host_idx < podman_idx
        ), "DOCKER_HOST check must appear before podman detection"
        assert (
            podman_idx < fallback_docker_idx
        ), "podman detection must appear before fallback docker detection"

    def test_pre_teardown_uses_down_v_with_error_suppression(self) -> None:
        """Pre-teardown runs ``down -v`` with ``2>/dev/null || true``."""
        script = _RUNNER_SCRIPT.read_text()
        lines = script.splitlines()

        suppressed = [
            line
            for line in lines
            if "down -v" in line and "2>/dev/null" in line and "|| true" in line
        ]
        assert (
            len(suppressed) >= 1
        ), "Pre-teardown must run 'down -v' with 2>/dev/null and || true"

    def test_uses_up_dash_dash_wait_test_database(self) -> None:
        """Container start uses ``up -d --wait test-database``."""
        script = _RUNNER_SCRIPT.read_text()

        assert (
            "up -d --wait test-database" in script
        ), "Missing 'up -d --wait test-database' command"
        assert "--wait" in script, "Missing --wait readiness flag"

    def test_no_sleep_used_for_readiness(self) -> None:
        """Script must not use ``sleep`` for container readiness."""
        script = _RUNNER_SCRIPT.read_text()

        assert (
            "sleep" not in script
        ), "sleep must not be used for readiness; use --wait instead"

    def test_targets_test_database_not_database_service(self) -> None:
        """Up command targets ``test-database``, not production ``database``."""
        script = _RUNNER_SCRIPT.read_text()

        assert (
            "up -d --wait test-database" in script
        ), "Must target test-database service"
        assert (
            "up -d --wait database" not in script
        ), "Must not target production database service directly"

    def test_run_group_handles_exit_code_5_as_non_failure(self) -> None:
        """run_group treats pytest exit 5 (no tests collected) as non-failure."""
        script = _RUNNER_SCRIPT.read_text()
        lines = script.splitlines()

        rc5_idx = _line_index(lines, "rc -eq 5")
        assert rc5_idx is not None, "Missing exit-code-5 handling (rc -eq 5)"

        # Collect the exit-5 block: lines after the elif until else/fi
        exit5_block: list[str] = []
        for i in range(rc5_idx + 1, len(lines)):
            stripped = lines[i].strip()
            if stripped == "else" or stripped == "fi" or stripped.startswith("elif"):
                break
            exit5_block.append(lines[i])

        exit5_text = "\n".join(exit5_block)
        assert (
            "EXIT_CODE=1" not in exit5_text
        ), "Exit-code-5 branch must not set EXIT_CODE=1"

    def test_run_group_handles_exit_code_nonzero_as_failure(self) -> None:
        """run_group treats non-zero (non-5) exit codes as failures."""
        script = _RUNNER_SCRIPT.read_text()
        lines = script.splitlines()

        rc5_idx = _line_index(lines, "rc -eq 5")
        assert rc5_idx is not None, "Missing exit-code-5 handling (rc -eq 5)"

        # Find the else (failure) branch after rc -eq 5
        else_idx: int | None = None
        for i in range(rc5_idx + 1, len(lines)):
            if lines[i].strip() == "else":
                else_idx = i
                break
        assert else_idx is not None, "Missing else (failure) branch after rc -eq 5"

        # Collect the else block until fi
        else_block: list[str] = []
        for i in range(else_idx + 1, len(lines)):
            if lines[i].strip() == "fi":
                break
            else_block.append(lines[i])

        else_text = "\n".join(else_block)
        assert "EXIT_CODE=1" in else_text, "Failure branch must set EXIT_CODE=1"

    def test_post_teardown_uses_down_v_without_error_suppression(self) -> None:
        """Post-teardown runs bare ``down -v`` without suppression."""
        script = _RUNNER_SCRIPT.read_text()
        lines = script.splitlines()

        down_v_lines = [line for line in lines if "down -v" in line]
        assert (
            len(down_v_lines) >= 2
        ), "Expected at least two down -v lines (pre and post teardown)"

        bare_lines = [
            line
            for line in down_v_lines
            if "2>/dev/null" not in line and "|| true" not in line
        ]
        assert (
            len(bare_lines) >= 1
        ), "Post-teardown down -v must not have error suppression"

    def test_teardown_ordering_pre_down_before_up_before_test_before_post_down(
        self,
    ) -> None:
        """Lifecycle order: pre-down -> up --wait -> run_group -> post-down."""
        script = _RUNNER_SCRIPT.read_text()
        lines = script.splitlines()

        pre_down = _line_index(lines, "down -v 2>/dev/null")
        assert pre_down is not None, "Pre-teardown down -v not found"

        up_wait = _line_index(lines, "up -d --wait test-database")
        assert up_wait is not None, "up -d --wait test-database not found"

        run_group_call = _line_index(lines, 'run_group "schema"')
        assert run_group_call is not None, "run_group call not found"

        # Find the LAST bare down -v line (post-teardown)
        post_down: int | None = None
        for i, line in enumerate(lines):
            if "down -v" in line and "2>/dev/null" not in line:
                post_down = i
        assert post_down is not None, "Post-teardown bare down -v not found"

        assert pre_down < up_wait, "Pre-teardown must come before up --wait"
        assert up_wait < run_group_call, "up --wait must come before run_group"
        assert run_group_call < post_down, "run_group must come before post-teardown"

    def test_uses_v2_compose_syntax_not_v1(self) -> None:
        """Script uses v2 ``docker compose``/``podman compose``, not v1 hyphen."""
        script = _RUNNER_SCRIPT.read_text()

        assert (
            "docker compose" in script or "podman compose" in script
        ), "Missing v2 compose syntax (space-separated)"
        assert (
            "docker-compose" not in script
        ), "Must not use v1 docker-compose (hyphenated) syntax"

    def test_makefile_test_postgres_delegates_to_script(self) -> None:
        """Makefile test-postgres target delegates to the lifecycle script."""
        makefile = _MAKEFILE.read_text()

        assert (
            "bash scripts/run-postgres-tests.sh" in makefile
        ), "test-postgres must run bash scripts/run-postgres-tests.sh"
        assert (
            "poetry run pytest --run-postgres" not in makefile
        ), "test-postgres must not run pytest --run-postgres inline"
