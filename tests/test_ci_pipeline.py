"""Structural test verifying ``.github/workflows/quality.yml`` CI pipeline.

Ensures that the CI workflow defines the expected jobs, triggers, and test
execution patterns.  This is a gatekeeper-level (G5) test that prevents
accidental regression of the CI pipeline structure.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import yaml

_REPO_ROOT: Path = Path(__file__).resolve().parent.parent

_REQUIRED_JOBS: list[str] = [
    "lint-and-typecheck",
    "unit-tests",
    "integration-tests",
    "gatekeeper",
]

_TEST_JOBS: list[str] = ["unit-tests", "integration-tests", "gatekeeper"]


def _load_ci_workflow() -> dict[str, Any]:
    """Parse ``.github/workflows/quality.yml`` and return as dict.

    Returns:
        Parsed workflow YAML as a dictionary.
    """
    with open(_REPO_ROOT / ".github" / "workflows" / "quality.yml") as f:
        data = yaml.safe_load(f)
    assert isinstance(data, dict)
    return cast("dict[str, Any]", data)


def _get_jobs(workflow: dict[str, Any]) -> dict[str, Any]:
    """Get the ``jobs`` mapping from a workflow dict.

    Args:
        workflow: Parsed workflow YAML.

    Returns:
        Mapping of job name to job definition.
    """
    jobs = workflow.get("jobs", {})
    assert isinstance(jobs, dict)
    return cast("dict[str, Any]", jobs)


def _get_job(workflow: dict[str, Any], job_name: str) -> dict[str, Any]:
    """Get a specific job definition by name.

    Args:
        workflow: Parsed workflow YAML.
        job_name: Name of the job to retrieve.

    Returns:
        Job definition dictionary.
    """
    jobs = _get_jobs(workflow)
    job = jobs.get(job_name)
    assert isinstance(job, dict), f"Job '{job_name}' not found"
    return cast("dict[str, Any]", job)


def _get_job_steps(workflow: dict[str, Any], job_name: str) -> list[dict[str, Any]]:
    """Get the ``steps`` list from a specific job.

    Args:
        workflow: Parsed workflow YAML.
        job_name: Name of the job whose steps to retrieve.

    Returns:
        List of step dictionaries.
    """
    job = _get_job(workflow, job_name)
    steps = job.get("steps", [])
    assert isinstance(steps, list)
    return cast("list[dict[str, Any]]", steps)


def _get_on_section(workflow: dict[str, Any]) -> dict[str, Any]:
    """Get the ``on`` trigger section from a workflow dict.

    YAML 1.1 parses the bare ``on`` key as boolean ``True``, so this helper
    checks for both ``True`` and the string ``"on"``.

    Args:
        workflow: Parsed workflow YAML.

    Returns:
        Trigger configuration dictionary.
    """
    raw = cast("dict[Any, Any]", workflow)
    on_section = raw.get(True)
    if on_section is None:
        on_section = raw.get("on")
    assert isinstance(on_section, dict), "Workflow 'on' section not found"
    return cast("dict[str, Any]", on_section)


def _find_step_with_run(
    steps: list[dict[str, Any]], substring: str
) -> dict[str, Any] | None:
    """Find the first step whose ``run`` field contains ``substring``.

    Args:
        steps: List of step dictionaries.
        substring: Substring to search for in the ``run`` field.

    Returns:
        The matching step dict, or ``None`` if not found.
    """
    for step in steps:
        assert isinstance(step, dict)
        run = step.get("run")
        if isinstance(run, str) and substring in run:
            return step
    return None


def _find_step_with_uses(
    steps: list[dict[str, Any]], substring: str
) -> dict[str, Any] | None:
    """Find the first step whose ``uses`` field contains ``substring``.

    Args:
        steps: List of step dictionaries.
        substring: Substring to search for in the ``uses`` field.

    Returns:
        The matching step dict, or ``None`` if not found.
    """
    for step in steps:
        assert isinstance(step, dict)
        uses = step.get("uses")
        if isinstance(uses, str) and substring in uses:
            return step
    return None


def _find_step_index_with_run(
    steps: list[dict[str, Any]], substring: str
) -> int | None:
    """Find the index of the first step whose ``run`` contains ``substring``.

    Args:
        steps: List of step dictionaries.
        substring: Substring to search for in the ``run`` field.

    Returns:
        The index of the matching step, or ``None`` if not found.
    """
    for idx, step in enumerate(steps):
        assert isinstance(step, dict)
        run = step.get("run")
        if isinstance(run, str) and substring in run:
            return idx
    return None


# ── Tests ──


def test_all_four_required_jobs_present() -> None:
    """Verify the workflow defines exactly the 4 required jobs (Coverage #11).

    Checks:
        - ``lint-and-typecheck``
        - ``unit-tests``
        - ``integration-tests``
        - ``gatekeeper``
    """
    workflow = _load_ci_workflow()
    jobs = _get_jobs(workflow)
    assert set(jobs.keys()) == set(
        _REQUIRED_JOBS
    ), f"Expected jobs {set(_REQUIRED_JOBS)}, got {set(jobs.keys())}"


def test_all_jobs_run_in_parallel_no_needs() -> None:
    """Verify all 4 jobs run in parallel with no ``needs`` dependency (Coverage #12).

    Checks:
        - No job has a ``needs`` key.
        - All jobs run on ``ubuntu-latest``.
    """
    workflow = _load_ci_workflow()
    for job_name in _REQUIRED_JOBS:
        job = _get_job(workflow, job_name)
        assert (
            "needs" not in job
        ), f"Job '{job_name}' should not have a 'needs' key (parallel execution)"
        assert (
            job.get("runs-on") == "ubuntu-latest"
        ), f"Job '{job_name}' should run on 'ubuntu-latest'"


def test_lint_job_includes_tests_in_ruff_and_black() -> None:
    """Verify the lint job runs ruff and black against ``tests/`` (Coverage #13).

    Checks:
        - The ruff step command contains ``tests/``.
        - The black step command contains ``tests/``.
    """
    workflow = _load_ci_workflow()
    steps = _get_job_steps(workflow, "lint-and-typecheck")

    ruff_step = _find_step_with_run(steps, "ruff check")
    assert ruff_step is not None, "Ruff step not found in lint-and-typecheck job"
    ruff_cmd = cast("str", ruff_step.get("run", ""))
    assert "tests/" in ruff_cmd, "Ruff command should include tests/"

    black_step = _find_step_with_run(steps, "black")
    assert black_step is not None, "Black step not found in lint-and-typecheck job"
    black_cmd = cast("str", black_step.get("run", ""))
    assert "tests/" in black_cmd, "Black command should include tests/"


def test_unit_tests_job_has_coverage_and_codecov() -> None:
    """Verify the unit-tests job has coverage and Codecov upload (Coverage #14).

    Checks:
        - A step with ``--cov=src`` exists and is gated on push events.
        - A step using ``codecov/codecov-action@v5`` exists and is gated on push.
    """
    workflow = _load_ci_workflow()
    steps = _get_job_steps(workflow, "unit-tests")

    cov_step = _find_step_with_run(steps, "--cov=src")
    assert cov_step is not None, "Coverage step (--cov=src) not found in unit-tests job"
    assert (
        cov_step.get("if") == "github.event_name == 'push'"
    ), "Coverage step should be gated on push events"

    codecov_step = _find_step_with_uses(steps, "codecov/codecov-action@v5")
    assert codecov_step is not None, "Codecov upload step not found in unit-tests job"
    assert (
        codecov_step.get("if") == "github.event_name == 'push'"
    ), "Codecov step should be gated on push events"


def test_gatekeeper_job_runs_checker_before_g5_tests() -> None:
    """Verify the gatekeeper job runs the checker script before G5 tests (Coverage #15).

    Checks:
        - The checker step runs ``bash scripts/check-test-hardcodes.sh all``.
        - The checker command does NOT contain ``|| true`` (must fail the build).
        - The G5 inversion step (``--ignore=tests/unit``) comes after the checker.
    """
    workflow = _load_ci_workflow()
    steps = _get_job_steps(workflow, "gatekeeper")

    checker_idx = _find_step_index_with_run(
        steps, "bash scripts/check-test-hardcodes.sh all"
    )
    assert checker_idx is not None, "Gatekeeper checker step not found"

    checker_step = steps[checker_idx]
    checker_cmd = cast("str", checker_step.get("run", ""))
    assert (
        "|| true" not in checker_cmd
    ), "Checker step must NOT contain '|| true' (must fail the build on error)"

    g5_idx = _find_step_index_with_run(steps, "--ignore=tests/unit")
    assert g5_idx is not None, "G5 inversion step not found"
    assert checker_idx < g5_idx, "Checker step must come before the G5 test step"


def test_all_test_jobs_use_correct_timeout_and_markers() -> None:
    """Verify all test jobs use ``--timeout=30`` and the slow/postgres markers (Coverage #16).

    Checks:
        - Every pytest step in ``unit-tests``, ``integration-tests``,
          ``gatekeeper`` contains ``--timeout=30``.
        - Every pytest step contains ``not slow and not postgres``.
    """
    workflow = _load_ci_workflow()
    for job_name in _TEST_JOBS:
        steps = _get_job_steps(workflow, job_name)
        pytest_steps: list[dict[str, Any]] = [
            step
            for step in steps
            if isinstance(step.get("run"), str) and "pytest" in cast("str", step["run"])
        ]
        assert (
            len(pytest_steps) > 0
        ), f"Job '{job_name}' should have at least one pytest step"
        for step in pytest_steps:
            cmd = cast("str", step["run"])
            assert (
                "--timeout=30" in cmd
            ), f"Job '{job_name}' pytest command should include --timeout=30: {cmd}"
            assert "not slow and not postgres" in cmd, (
                f"Job '{job_name}' pytest command should include "
                f"'not slow and not postgres' marker: {cmd}"
            )


def test_workflow_has_required_push_and_pr_triggers() -> None:
    """Verify the workflow triggers on push and PR to ``main`` (Coverage #17).

    Checks:
        - ``push`` trigger exists with ``branches`` containing ``main``.
        - ``pull_request`` trigger exists with ``branches`` containing ``main``.
    """
    workflow = _load_ci_workflow()
    on_section = _get_on_section(workflow)

    push = on_section.get("push")
    assert isinstance(push, dict), "push trigger not found in 'on' section"
    push_dict = cast("dict[str, Any]", push)
    push_branches = cast("list[str]", push_dict.get("branches", []))
    assert "main" in push_branches, "push trigger should target 'main' branch"

    pr = on_section.get("pull_request")
    assert isinstance(pr, dict), "pull_request trigger not found in 'on' section"
    pr_dict = cast("dict[str, Any]", pr)
    pr_branches = cast("list[str]", pr_dict.get("branches", []))
    assert "main" in pr_branches, "pull_request trigger should target 'main' branch"


def test_nightly_ci_run_at_03_00_utc() -> None:
    """Verify the workflow has a nightly schedule at 03:00 UTC (Coverage #18).

    Checks:
        - ``schedule`` trigger exists.
        - The schedule contains a cron entry with value ``0 3 * * *``.
    """
    workflow = _load_ci_workflow()
    on_section = _get_on_section(workflow)

    schedule = on_section.get("schedule")
    assert isinstance(schedule, list), "schedule trigger not found in 'on' section"
    schedule_list = cast("list[Any]", schedule)

    cron_values: list[str] = []
    for entry in schedule_list:
        if isinstance(entry, dict):
            entry_dict = cast("dict[str, Any]", entry)
            cron_values.append(cast("str", entry_dict.get("cron", "")))
    assert (
        "0 3 * * *" in cron_values
    ), "Schedule should include a cron entry '0 3 * * *' (daily at 03:00 UTC)"
