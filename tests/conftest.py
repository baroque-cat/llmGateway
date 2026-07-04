"""Global test configuration.

Provides CanonicalConfig-based environment setup and gatekeeper cache fixtures.
Replaces the old ``os.environ.setdefault()`` pattern with a frozen dataclass
single source of truth.
"""

from __future__ import annotations

import hashlib
import subprocess
import types
from collections.abc import Callable
from pathlib import Path
from typing import NamedTuple

import pytest

from tests._canonical import CanonicalConfig

# ── CanonicalConfig fixtures ──


@pytest.fixture(scope="session")
def canonical_config() -> CanonicalConfig:
    """Frozen canonical configuration parsed once per test session.

    Returns:
        CanonicalConfig instance from ``.env.example`` + YAML.
    """
    return CanonicalConfig.from_example_files()


@pytest.fixture(autouse=True)
def _set_config_vars_from_canonical(  # pyright: ignore[reportUnusedFunction]
    monkeypatch: pytest.MonkeyPatch, canonical_config: CanonicalConfig
) -> None:
    """Set ALL 17 env vars from CanonicalConfig before every test.

    Uses ``monkeypatch.setenv`` for pytest-native isolation (changes are
    reverted after each test).  Tests needing different values can override
    with their own ``monkeypatch.setenv`` or ``patch.dict``.
    """
    monkeypatch.setenv("DB_HOST", canonical_config.db_host)
    monkeypatch.setenv("DB_PORT", str(canonical_config.db_port))
    monkeypatch.setenv("DB_USER", canonical_config.db_user)
    monkeypatch.setenv("DB_PASSWORD", canonical_config.db_password)
    monkeypatch.setenv("DB_NAME", canonical_config.db_name)
    monkeypatch.setenv("GATEWAY_HOST", canonical_config.gateway_host)
    monkeypatch.setenv("GATEWAY_PORT", str(canonical_config.gateway_port))
    monkeypatch.setenv("GATEWAY_WORKERS", str(canonical_config.gateway_workers))
    monkeypatch.setenv("KEEPER_METRICS_PORT", str(canonical_config.keeper_metrics_port))
    monkeypatch.setenv("METRICS_ACCESS_TOKEN", canonical_config.metrics_access_token)
    monkeypatch.setenv("METRICS_BACKEND", canonical_config.metrics_backend)
    monkeypatch.setenv(
        "PROMETHEUS_MULTIPROC_DIR", canonical_config.prometheus_multiproc_dir
    )
    monkeypatch.setenv(
        "LLM_PROVIDER_DEFAULT_TOKEN", canonical_config.llm_provider_default_token
    )
    monkeypatch.setenv("GEMINI_PROD_TOKEN", canonical_config.gemini_prod_token)
    monkeypatch.setenv("DEEPSEEK_TOKEN", canonical_config.deepseek_token)
    monkeypatch.setenv("ANTHROPIC_TOKEN", canonical_config.anthropic_token)
    monkeypatch.setenv("QWEN_HOME_TOKEN", canonical_config.qwen_home_token)


# ── Custom CLI options ──


def pytest_addoption(parser: pytest.Parser) -> None:
    """Register custom CLI options for the test suite.

    --run-postgres: opt-in flag for tests requiring a live PostgreSQL instance.
    Without this flag, postgres-marked tests are skipped.
    """
    parser.addoption(
        "--run-postgres",
        action="store_true",
        default=False,
        help="Run tests marked with @pytest.mark.postgres",
    )


def pytest_configure(config: pytest.Config) -> None:
    """Register custom markers during pytest configuration."""
    config.addinivalue_line(
        "markers", "postgres: tests requiring a live PostgreSQL instance"
    )


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    """Skip postgres-marked tests unless --run-postgres is set."""
    if not config.getoption("--run-postgres"):
        skip_postgres = pytest.mark.skip(reason="--run-postgres not specified")
        for item in items:
            if "postgres" in item.keywords:
                item.add_marker(skip_postgres)


# ── Gatekeeper fixtures ──


class CheckerResult(NamedTuple):
    """Result of running the gatekeeper script in a specific mode."""

    returncode: int
    stdout: str
    stderr: str


_REPO_ROOT: Path = Path(__file__).resolve().parent.parent
_CHECKER_SCRIPT: Path = _REPO_ROOT / "scripts" / "check-test-hardcodes.sh"

_CHECKER_SCAN_DIRS: list[Path] = [
    Path("tests/unit"),
    Path("tests/integration"),
    Path("tests/security"),
    Path("tests/e2e"),
    Path("tests/stress"),
    Path("tests/batching"),
    Path("tests"),
]

_SUMMARY_LINE: str = "\nAll test hardcode checks passed\n\n"

type _CheckerCache = types.MappingProxyType[str, CheckerResult]


@pytest.fixture(scope="session")
def _cached_checker_results() -> _CheckerCache:  # pyright: ignore[reportUnusedFunction]
    """Run check-test-hardcodes.sh once per mode. Cached in memory.

    Returns:
        Read-only mapping of mode → CheckerResult.
    """
    results: dict[str, CheckerResult] = {}
    for mode in ("canonical", "boundary", "root"):
        proc = subprocess.run(  # noqa: S603
            ["bash", str(_CHECKER_SCRIPT), mode],  # noqa: S603
            capture_output=True,
            text=True,
            cwd=str(_REPO_ROOT),
            timeout=60,
        )
        results[mode] = CheckerResult(
            returncode=proc.returncode,
            stdout=proc.stdout,
            stderr=proc.stderr,
        )
    return types.MappingProxyType(results)


@pytest.fixture
def checker_result(
    _cached_checker_results: types.MappingProxyType[str, CheckerResult],
) -> Callable[..., CheckerResult]:
    """Function-scoped accessor for cached checker results.

    Returns a callable that accepts a mode string (``"canonical"``,
    ``"boundary"``, ``"root"``, or ``"all"``) and returns the cached
    ``CheckerResult``.
    """

    def _get_result(mode: str = "all") -> CheckerResult:
        if mode == "all":
            canonical = _cached_checker_results["canonical"]
            boundary = _cached_checker_results["boundary"]
            root = _cached_checker_results["root"]
            combined_rc = max(
                canonical.returncode, boundary.returncode, root.returncode
            )
            combined_stdout = (
                canonical.stdout.removesuffix(_SUMMARY_LINE)
                + boundary.stdout.removesuffix(_SUMMARY_LINE)
                + root.stdout.removesuffix(_SUMMARY_LINE)
                + _SUMMARY_LINE
            )
            combined_stderr = canonical.stderr + boundary.stderr + root.stderr
            return CheckerResult(combined_rc, combined_stdout, combined_stderr)
        if mode not in _cached_checker_results:
            raise ValueError(
                f"Unknown checker mode: {mode!r}. "
                "Valid: canonical, boundary, root, all"
            )
        return _cached_checker_results[mode]

    return _get_result


@pytest.fixture(scope="session", autouse=True)
def _cleanup_stale_temp_files() -> None:  # pyright: ignore[reportUnusedFunction]
    """Remove stale temp files from crashed sessions."""
    try:
        for scan_dir_rel in _CHECKER_SCAN_DIRS:
            full_dir = _REPO_ROOT / scan_dir_rel
            if not full_dir.is_dir():
                continue
            for stale in full_dir.rglob("tmp*.py"):
                if stale.is_file():
                    stale.unlink(missing_ok=True)
    except OSError:
        pass


def _compute_checker_hash() -> str:  # pyright: ignore[reportUnusedFunction]
    """Compute sha256 of check-test-hardcodes.sh + all scanned .py files.

    Returns:
        Hex digest string.
    """
    hasher = hashlib.sha256()
    hasher.update(_CHECKER_SCRIPT.read_bytes())
    seen: set[Path] = set()
    for scan_dir in _CHECKER_SCAN_DIRS:
        full_dir = _REPO_ROOT / scan_dir
        if not full_dir.is_dir():
            continue
        for py_file in sorted(full_dir.rglob("*.py")):
            if "__pycache__" in py_file.parts or py_file.name == "__init__.py":
                continue
            resolved = py_file.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            hasher.update(py_file.read_bytes())
    return hasher.hexdigest()
