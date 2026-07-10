"""CanonicalConfig — single source of truth for test configuration.

Parses ``.env.example`` and ``config/example_full_config.yaml`` deterministically
at import time via ``ruamel.yaml``.  Returns a frozen dataclass with ~50 typed
fields covering every configuration section.

Design note — test-safe overrides
---------------------------------
``.env.example`` contains *production* placeholder values (e.g.
``DB_PASSWORD=your_secure_password_here``, empty provider tokens).  Using those
verbatim in the test autouse fixture would break hundreds of existing tests that
expect mock tokens such as ``test_gemini_token``.

CanonicalConfig therefore parses ``.env.example`` to discover the *set* of env
var keys and non-sensitive values (hosts, ports, etc.), but overrides
sensitive fields (DB credentials, provider tokens, metrics access token) with
test-safe mock values from :mod:`tests._constants`.  This satisfies both spec
requirements:

1. CanonicalConfig *parses* ``.env.example`` (reads keys + non-sensitive values).
2. All existing tests continue to pass with the same environment variable values.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

from ruamel.yaml import YAML

from tests._constants import (
    MOCK_ANTHROPIC_TOKEN,
    MOCK_DEEPSEEK_TOKEN,
    MOCK_DEFAULT_TOKEN,
    MOCK_GEMINI_TOKEN,
    MOCK_METRICS_TOKEN,
    MOCK_QWEN_TOKEN,
)

# ── Project paths ──

_PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent
_ENV_EXAMPLE: Path = _PROJECT_ROOT / ".env.example"
_CONFIG_EXAMPLE: Path = _PROJECT_ROOT / "config" / "example_full_config.yaml"

# ── Placeholder resolution ──

_ENV_VAR_RE: re.Pattern[str] = re.compile(r"\$\{([A-Z_][A-Z0-9_]*)(?::-([^}]*))?\}")

# ── Test-safe overrides for sensitive env vars ──
# These replace production placeholder values from .env.example with mock
# tokens that existing tests expect.

_TEST_SAFE_OVERRIDES: dict[str, str] = {
    "DB_USER": "test_user",
    "DB_PASSWORD": "test_password",
    "DB_NAME": "test_db",
    "METRICS_ACCESS_TOKEN": MOCK_METRICS_TOKEN,
    "LLM_PROVIDER_DEFAULT_TOKEN": MOCK_DEFAULT_TOKEN,
    "GEMINI_PROD_TOKEN": MOCK_GEMINI_TOKEN,
    "DEEPSEEK_TOKEN": MOCK_DEEPSEEK_TOKEN,
    "ANTHROPIC_TOKEN": MOCK_ANTHROPIC_TOKEN,
    "QWEN_HOME_TOKEN": MOCK_QWEN_TOKEN,
}

# ── Module-level caches (lazy singletons) ──

_env_cache: dict[str, str] | None = None
_config_cache: dict[str, Any] | None = None


# ── Parsing pipeline ──


def _load_env_example() -> dict[str, str]:
    """Parse ``.env.example`` into a ``dict[str, str]``.

    Skips comment lines (starting with ``#``) and blank lines.
    Strips inline comments (everything after ``#``) and whitespace
    from both keys and values.

    Returns:
        Mapping of env var name to its raw string value from ``.env.example``.
    """
    result: dict[str, str] = {}
    for raw_line in _ENV_EXAMPLE.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        # Strip inline comment (e.g. ``DB_HOST=localhost # comment``)
        if "#" in value:
            value = value.split("#", 1)[0]
        result[key.strip()] = value.strip()
    return result


def _load_config_example() -> dict[str, Any]:
    """Parse ``config/example_full_config.yaml`` via ``ruamel.yaml``.

    Returns:
        Parsed YAML as a regular ``dict[str, Any]`` (no comment preservation).
    """
    yaml = YAML(typ="safe")
    # fmt: off
    data = cast(dict[str, Any] | None, yaml.load(_CONFIG_EXAMPLE.read_text(encoding="utf-8")))  # pyright: ignore[reportUnknownMemberType]
    # fmt: on
    if data is None:
        return {}
    return data


def _resolve_config_placeholders(data: Any, env: dict[str, str]) -> Any:
    """Recursively resolve ``${VAR}`` and ``${VAR:-default}`` placeholders.

    Args:
        data: Parsed YAML data (dict, list, str, or scalar).
        env: Environment variable mapping for placeholder resolution.

    Returns:
        Data with all placeholders resolved (same structure, new objects).
    """
    if isinstance(data, dict):
        # fmt: off
        return {str(k): _resolve_config_placeholders(v, env) for k, v in data.items()}  # pyright: ignore[reportUnknownVariableType,reportUnknownArgumentType]
        # fmt: on
    if isinstance(data, list):
        # fmt: off
        return [_resolve_config_placeholders(item, env) for item in data]  # pyright: ignore[reportUnknownVariableType]
        # fmt: on
    if isinstance(data, str):

        def _replace(match: re.Match[str]) -> str:
            var_name: str = match.group(1)
            default: str | None = match.group(2)
            if var_name in env:
                return env[var_name]
            if default is not None:
                return default
            return match.group(0)

        return _ENV_VAR_RE.sub(_replace, data)
    return data


def _get_env() -> dict[str, str]:
    """Return cached env dict from ``.env.example`` with test-safe overrides.

    Parses ``.env.example`` once (lazy singleton) and applies
    ``_TEST_SAFE_OVERRIDES`` for sensitive fields.
    """
    global _env_cache
    if _env_cache is None:
        raw = _load_env_example()
        _env_cache = {**raw, **_TEST_SAFE_OVERRIDES}
    return _env_cache


def _get_config() -> dict[str, Any]:
    """Return cached, placeholder-resolved config dict from YAML.

    Parses ``config/example_full_config.yaml`` once (lazy singleton),
    resolves ``${VAR}`` placeholders using the env dict.
    """
    global _config_cache
    if _config_cache is None:
        raw = _load_config_example()
        env = _get_env()
        resolved = _resolve_config_placeholders(raw, env)
        _config_cache = cast(dict[str, Any], resolved)
    return _config_cache


def _get_nested(data: dict[str, Any], *keys: str, default: Any = None) -> Any:
    """Safely navigate nested dict by keys.

    Args:
        data: Top-level dict.
        *keys: Sequence of keys to traverse.
        default: Value to return if any key is missing.

    Returns:
        Value at the nested path, or ``default`` if not found.
    """
    current: dict[str, Any] = data
    for key in keys:
        if key not in current:
            return default
        value = current[key]
        if value is None:
            return default
        if isinstance(value, dict):
            current = cast(dict[str, Any], value)
        else:
            return value
    return current


def _first_provider_with(data: dict[str, Any], *fields: str) -> dict[str, Any]:
    """Find the first provider config that contains all given fields.

    Args:
        data: Parsed config dict.
        *fields: Field names the provider must have (e.g. ``"timeouts"``).

    Returns:
        First matching provider config dict, or empty dict if none found.
    """
    providers: Any = data.get("providers", {})
    if not isinstance(providers, dict):
        return {}
    # fmt: off
    for provider_cfg in providers.values():  # pyright: ignore[reportUnknownVariableType]
        if not isinstance(provider_cfg, dict):
            continue
        if all(f in provider_cfg for f in fields):
            return cast(dict[str, Any], provider_cfg)
    # fmt: on
    return {}


def _dict_or_empty(value: Any) -> dict[str, Any]:
    """Return ``value`` as a dict, or empty dict if not a dict."""
    if isinstance(value, dict):
        return cast(dict[str, Any], value)
    return {}


# ── CanonicalConfig dataclass ──


@dataclass(frozen=True)
class CanonicalConfig:
    """Frozen dataclass holding all canonical test configuration values.

    Parsed deterministically from ``.env.example`` and
    ``config/example_full_config.yaml``.  Sensitive fields (DB credentials,
    provider tokens) use test-safe mock values from :mod:`tests._constants`.

    Fields:
        db_host: Database host (from .env.example).
        db_port: Database port (from .env.example).
        db_user: Database user (test-safe: ``test_user``).
        db_password: Database password (test-safe: ``test_password``).
        db_name: Database name (test-safe: ``test_db``).
        db_pool_min_size: Minimum connection pool size (from YAML).
        db_pool_max_size: Maximum connection pool size (from YAML).
        db_pool_command_timeout: Per-query timeout in seconds (from YAML).
        db_pool_timeout: TCP connect timeout in seconds (from YAML).
        db_retry_max_attempts: Max retry attempts for transient DB errors.
        db_retry_base_delay_sec: Base delay before first retry.
        db_retry_backoff_factor: Exponential backoff multiplier.
        db_retry_jitter: Whether to add random jitter to retries.
        db_vacuum_interval_minutes: Interval between vacuum health checks.
        db_vacuum_dead_tuple_ratio_threshold: Dead tuple ratio trigger.
        gateway_host: Gateway bind host (from .env.example).
        gateway_port: Gateway bind port (from .env.example).
        gateway_workers: Number of Uvicorn workers (from .env.example).
        keeper_metrics_port: Keeper metrics port (from .env.example).
        keeper_max_concurrent_providers: Keeper concurrency limit (from YAML).
        http2_enabled: Whether HTTP/2 is enabled for upstream connections.
        pool_max_connections: Max connections in HTTP connection pool.
        pool_max_keepalive: Max keepalive connections in HTTP pool.
        pool_keepalive_expiry: Keepalive expiry in seconds.
        timeout_connect: Provider connect timeout in seconds.
        timeout_read: Provider read timeout in seconds.
        timeout_write: Provider write timeout in seconds.
        timeout_pool: Provider pool timeout in seconds.
        timeout_total: Provider total request timeout in seconds.
        timeout_stream_read: Per-stream response header timeout in seconds
            (None = no per-stream deadline, socket-level read timeout remains).
        metrics_enabled: Whether the /metrics endpoint is enabled.
        metrics_access_token: Metrics access token (test-safe mock).
        metrics_backend: Metrics backend (``""`` for memory/disabled).
        prometheus_multiproc_dir: Multiprocess directory (``""`` for single-process).
        llm_provider_default_token: Default provider token (test-safe mock).
        gemini_prod_token: Gemini provider token (test-safe mock).
        deepseek_token: DeepSeek provider token (test-safe mock).
        anthropic_token: Anthropic provider token (test-safe mock).
        qwen_home_token: Qwen provider token (test-safe mock).
        adaptive_start_batch_size: Initial batch size for adaptive controller.
        adaptive_start_batch_delay_sec: Initial batch delay in seconds.
        adaptive_min_batch_size: Lower bound for batch size.
        adaptive_max_batch_size: Upper bound for batch size.
        adaptive_min_batch_delay_sec: Minimum pause between batches.
        adaptive_max_batch_delay_sec: Maximum pause under throttling.
        task_timeout_sec: Max seconds a single probe task can run.
        verification_attempts: Re-verification count for retryable errors.
        verification_delay_sec: Delay between verification attempts.
        purge_after_days: Days before a stopped key is purged.
        canonical_provider_types: Tuple of valid provider type strings.
        canonical_model_names: Tuple of valid model name strings.
    """

    # === Database (5) ===
    db_host: str
    db_port: int
    db_user: str
    db_password: str
    db_name: str

    # === Database Pool (4) ===
    db_pool_min_size: int
    db_pool_max_size: int
    db_pool_command_timeout: float
    db_pool_timeout: float

    # === Database Retry (4) ===
    db_retry_max_attempts: int
    db_retry_base_delay_sec: float
    db_retry_backoff_factor: float
    db_retry_jitter: bool

    # === Database Vacuum (2) ===
    db_vacuum_interval_minutes: int
    db_vacuum_dead_tuple_ratio_threshold: float

    # === Gateway (3) ===
    gateway_host: str
    gateway_port: int
    gateway_workers: int

    # === Keeper (2) ===
    keeper_metrics_port: int
    keeper_max_concurrent_providers: int

    # === HTTP Client (4) ===
    http2_enabled: bool
    pool_max_connections: int
    pool_max_keepalive: int
    pool_keepalive_expiry: float

    # === Timeouts (6) ===
    timeout_connect: float
    timeout_read: float
    timeout_write: float
    timeout_pool: float
    timeout_total: float
    timeout_stream_read: float | None

    # === Metrics (4) ===
    metrics_enabled: bool
    metrics_access_token: str
    metrics_backend: str
    prometheus_multiproc_dir: str

    # === Provider tokens (5) ===
    llm_provider_default_token: str
    gemini_prod_token: str
    deepseek_token: str
    anthropic_token: str
    qwen_home_token: str

    # === Adaptive Batching (6) ===
    adaptive_start_batch_size: int
    adaptive_start_batch_delay_sec: float
    adaptive_min_batch_size: int
    adaptive_max_batch_size: int
    adaptive_min_batch_delay_sec: float
    adaptive_max_batch_delay_sec: float

    # === Health Policy (4) ===
    task_timeout_sec: int
    verification_attempts: int
    verification_delay_sec: int
    purge_after_days: int

    # === Canonical lists (2) ===
    canonical_provider_types: tuple[str, ...] = field(
        default_factory=lambda: ("anthropic", "openai_like", "gemini")
    )
    canonical_model_names: tuple[str, ...] = field(
        default_factory=lambda: (
            "gemini-2.5-flash",
            "gemini-2.5-pro",
            "claude-sonnet-4-20250514",
            "claude-opus-4-20250514",
            "deepseek-chat",
            "qwen3-max-2026-01-23",
        )
    )

    @classmethod
    def from_example_files(cls) -> CanonicalConfig:
        """Construct a CanonicalConfig from ``.env.example`` and YAML.

        Parses both files (cached at module level), resolves ``${VAR}``
        placeholders, and returns a frozen dataclass instance.

        Returns:
            Frozen CanonicalConfig instance with ~50 typed fields.
        """
        env = _get_env()
        cfg = _get_config()

        # Navigate nested YAML sections
        db = _dict_or_empty(_get_nested(cfg, "database", default={}))
        db_pool = _dict_or_empty(db.get("pool", {}))
        db_retry = _dict_or_empty(db.get("retry", {}))
        db_vacuum = _dict_or_empty(db.get("vacuum_policy", {}))
        keeper = _dict_or_empty(_get_nested(cfg, "keeper", default={}))
        http_client = _dict_or_empty(_get_nested(cfg, "http_client", default={}))
        http_pool = _dict_or_empty(http_client.get("pool", {}))
        metrics = _dict_or_empty(_get_nested(cfg, "metrics", default={}))

        # Extract from first provider that has timeouts + worker_health_policy
        provider = _first_provider_with(cfg, "timeouts", "worker_health_policy")
        timeouts = _dict_or_empty(provider.get("timeouts", {}))
        whp = _dict_or_empty(provider.get("worker_health_policy", {}))
        adaptive = _dict_or_empty(whp.get("adaptive_batching", {}))
        purge = _dict_or_empty(whp.get("purge", {}))

        return cls(
            # Database (from env vars, with test-safe overrides)
            db_host=env["DB_HOST"],
            db_port=int(env["DB_PORT"]),
            db_user=env["DB_USER"],
            db_password=env["DB_PASSWORD"],
            db_name=env["DB_NAME"],
            # Database Pool (from YAML)
            db_pool_min_size=int(db_pool.get("min_size", 1)),
            db_pool_max_size=int(db_pool.get("max_size", 15)),
            db_pool_command_timeout=float(db_pool.get("command_timeout", 30.0)),
            db_pool_timeout=float(db_pool.get("timeout", 60.0)),
            # Database Retry (from YAML)
            db_retry_max_attempts=int(db_retry.get("max_attempts", 3)),
            db_retry_base_delay_sec=float(db_retry.get("base_delay_sec", 1.0)),
            db_retry_backoff_factor=float(db_retry.get("backoff_factor", 2.0)),
            db_retry_jitter=bool(db_retry.get("jitter", True)),
            # Database Vacuum (from YAML)
            db_vacuum_interval_minutes=int(db_vacuum.get("interval_minutes", 60)),
            db_vacuum_dead_tuple_ratio_threshold=float(
                db_vacuum.get("dead_tuple_ratio_threshold", 0.3)
            ),
            # Gateway (from env vars)
            gateway_host=env["GATEWAY_HOST"],
            gateway_port=int(env["GATEWAY_PORT"]),
            gateway_workers=int(env["GATEWAY_WORKERS"]),
            # Keeper (port from env, concurrency from YAML)
            keeper_metrics_port=int(env["KEEPER_METRICS_PORT"]),
            keeper_max_concurrent_providers=int(
                keeper.get("max_concurrent_providers", 10)
            ),
            # HTTP Client (from YAML)
            http2_enabled=bool(http_client.get("http2", True)),
            pool_max_connections=int(http_pool.get("max_connections", 200)),
            pool_max_keepalive=int(http_pool.get("max_keepalive_connections", 50)),
            pool_keepalive_expiry=float(http_pool.get("keepalive_expiry", 30.0)),
            # Timeouts (from YAML, first provider with timeouts)
            timeout_connect=float(timeouts.get("connect", 10.0)),
            timeout_read=float(timeouts.get("read", 120.0)),
            timeout_write=float(timeouts.get("write", 20.0)),
            timeout_pool=float(timeouts.get("pool", 15.0)),
            timeout_total=float(timeouts.get("total", 600.0)),
            timeout_stream_read=(
                float(timeouts["stream_read"])
                if timeouts.get("stream_read") is not None
                else None
            ),
            # Metrics (enabled from YAML, token from env, backend/dir from env)
            metrics_enabled=bool(metrics.get("enabled", True)),
            metrics_access_token=env["METRICS_ACCESS_TOKEN"],
            metrics_backend=env["METRICS_BACKEND"],
            prometheus_multiproc_dir=env["PROMETHEUS_MULTIPROC_DIR"],
            # Provider tokens (from env, with test-safe overrides)
            llm_provider_default_token=env["LLM_PROVIDER_DEFAULT_TOKEN"],
            gemini_prod_token=env["GEMINI_PROD_TOKEN"],
            deepseek_token=env["DEEPSEEK_TOKEN"],
            anthropic_token=env["ANTHROPIC_TOKEN"],
            qwen_home_token=env["QWEN_HOME_TOKEN"],
            # Adaptive Batching (from YAML, first provider)
            adaptive_start_batch_size=int(adaptive.get("start_batch_size", 10)),
            adaptive_start_batch_delay_sec=float(
                adaptive.get("start_batch_delay_sec", 30.0)
            ),
            adaptive_min_batch_size=int(adaptive.get("min_batch_size", 5)),
            adaptive_max_batch_size=int(adaptive.get("max_batch_size", 50)),
            adaptive_min_batch_delay_sec=float(
                adaptive.get("min_batch_delay_sec", 3.0)
            ),
            adaptive_max_batch_delay_sec=float(
                adaptive.get("max_batch_delay_sec", 120.0)
            ),
            # Health Policy (from YAML, first provider)
            task_timeout_sec=int(whp.get("task_timeout_sec", 900)),
            verification_attempts=int(whp.get("verification_attempts", 3)),
            verification_delay_sec=int(whp.get("verification_delay_sec", 65)),
            purge_after_days=int(purge.get("after_days", 180)),
        )

    def to_env_dict(self) -> dict[str, str]:
        """Return all 17 env vars as a ``dict[str, str]``.

        Convenience method for tests that need to ``patch.dict(os.environ, ...)``
        with the canonical environment.  Keys match ``.env.example`` variable
        names; values are stringified CanonicalConfig fields (with test-safe
        overrides already applied).

        Returns:
            Mapping of 17 env var names to their canonical string values.
        """
        return {
            "DB_HOST": self.db_host,
            "DB_PORT": str(self.db_port),
            "DB_USER": self.db_user,
            "DB_PASSWORD": self.db_password,
            "DB_NAME": self.db_name,
            "GATEWAY_HOST": self.gateway_host,
            "GATEWAY_PORT": str(self.gateway_port),
            "GATEWAY_WORKERS": str(self.gateway_workers),
            "KEEPER_METRICS_PORT": str(self.keeper_metrics_port),
            "METRICS_ACCESS_TOKEN": self.metrics_access_token,
            "METRICS_BACKEND": self.metrics_backend,
            "PROMETHEUS_MULTIPROC_DIR": self.prometheus_multiproc_dir,
            "LLM_PROVIDER_DEFAULT_TOKEN": self.llm_provider_default_token,
            "GEMINI_PROD_TOKEN": self.gemini_prod_token,
            "DEEPSEEK_TOKEN": self.deepseek_token,
            "ANTHROPIC_TOKEN": self.anthropic_token,
            "QWEN_HOME_TOKEN": self.qwen_home_token,
        }
