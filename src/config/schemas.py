#!/usr/bin/env python3

import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# Import core enums for type hints and validation in schemas.
# Pydantic will automatically validate enum values at runtime.
from src.core.constants import (
    CircuitBreakerMode,
    DebugMode,
    ErrorReason,
    ProviderType,
    ProxyMode,
    Status,
    StreamingMode,
)
from src.core.models import AdaptiveBatchingParams

# ==============================================================================
# 1. ATOMIC AND NESTED CONFIGURATION CLASSES
# ==============================================================================
# This follows Step 1 and 2 of the plan: define the smallest building blocks first.
# These will be nested within larger configuration objects.


class ModelInfo(BaseModel):
    """
    Represents the specific configuration for a single model within a provider.
    This enables a config-driven approach for handling multimodal APIs.
    """

    # The suffix appended to the provider's base URL to form the full endpoint.
    # e.g., ":generateContent" for Gemini text, "/chat/completions" for OpenAI.
    endpoint_suffix: str = ""

    # The minimal, valid JSON payload required to perform a health check on this model.
    # Using default_factory=dict to avoid mutable default issues. This is crucial
    # and directly addresses a point from the "Potential Errors" analysis.
    test_payload: dict[str, Any] = Field(default_factory=dict)


class AccessControlConfig(BaseModel):
    """
    Configuration for gateway access control for a specific provider instance.
    """

    # The token that client applications must provide in the Authorization header
    # to use this specific provider instance through the gateway.
    gateway_access_token: str = ""


class RetryOnErrorConfig(BaseModel):
    """Defines retry behavior for a specific error category (e.g., server errors)."""

    # Number of retry attempts for this error type. 0 means no retries.
    attempts: int = Field(default=0, ge=0)
    # Initial delay in seconds before the first retry.
    backoff_sec: float = Field(default=0.1, ge=0)
    # Multiplier for the delay for subsequent retries (e.g., 2.0 for exponential backoff).
    backoff_factor: float = Field(default=1.5, ge=1.0)


class RetryPolicyConfig(BaseModel):
    """Container for the gateway's request retry policies."""

    enabled: bool = False
    # Specific retry settings for when a key is invalid, out of quota, etc.
    on_key_error: RetryOnErrorConfig = Field(default_factory=RetryOnErrorConfig)
    # Specific retry settings for 5xx server-side errors.
    on_server_error: RetryOnErrorConfig = Field(default_factory=RetryOnErrorConfig)

    @model_validator(mode="after")
    def check_retry_meaningful(self) -> "RetryPolicyConfig":
        """If retry is enabled, at least one error category must have attempts >= 1."""
        if (
            self.enabled
            and self.on_key_error.attempts < 1
            and self.on_server_error.attempts < 1
        ):
            raise ValueError(
                "retry.enabled is True but both on_key_error.attempts and "
                "on_server_error.attempts are 0. At least one must be >= 1."
            )
        return self


class BackoffConfig(BaseModel):
    """Configuration for the exponential backoff strategy of the circuit breaker."""

    # The initial duration in seconds to wait after the circuit opens.
    base_duration_sec: int = Field(default=30, gt=0)
    # The maximum duration the backoff can reach.
    max_duration_sec: int = Field(default=1800, gt=0)
    # The factor by which the duration increases after each failed check.
    factor: float = Field(default=2.0, ge=1.0)

    @model_validator(mode="after")
    def check_bounds(self) -> "BackoffConfig":
        """Validate base_duration_sec <= max_duration_sec."""
        if self.base_duration_sec > self.max_duration_sec:
            raise ValueError(
                f"base_duration_sec ({self.base_duration_sec}) must be <= "
                f"max_duration_sec ({self.max_duration_sec})"
            )
        return self


class CircuitBreakerConfig(BaseModel):
    """
    Configuration for the Circuit Breaker mechanism to prevent cascading failures.
    """

    enabled: bool = False
    # 'auto_recovery' will periodically re-test the endpoint.
    # 'manual_reset' requires external intervention to close the circuit.
    mode: CircuitBreakerMode = CircuitBreakerMode.AUTO_RECOVERY
    # The number of consecutive failures required to open the circuit.
    failure_threshold: int = Field(default=10, gt=0)
    # Configuration for the backoff strategy when the circuit is open.
    backoff: BackoffConfig = Field(default_factory=BackoffConfig)
    # A random delay added to backoff to prevent thundering herd problems.
    jitter_sec: int = Field(default=5, ge=0)


class MetricsConfig(BaseModel):
    """
    Configuration for the Prometheus metrics exporter.
    """

    # Enables or disables the /metrics endpoint
    enabled: bool = True

    # The Bearer token required to access the /metrics endpoint
    access_token: str = ""


# ==============================================================================
# 2. MAIN CONFIGURATION SECTIONS
# ==============================================================================
# This follows Step 3 and 4 of the plan. These are the main "optional" blocks
# and the global configuration sections.


class AdaptiveBatchingConfig(BaseModel):
    """
    Configuration for adaptive batch sizing in the background worker.

    Replaces static ``batch_size`` / ``batch_delay_sec`` with a self-tuning
    controller that adjusts batch size and delay based on the results of each
    completed batch. The existing ``batch_size`` and ``batch_delay_sec`` fields
    serve as initial values for the controller.

    **Algorithm Summary**:

    1. **Rate-limited** (RATE_LIMITED in batch) → aggressive backoff:
       ``batch_size //= rate_limit_divisor``, ``delay *= rate_limit_delay_multiplier``.
    2. **Transient errors** (>failure_rate_threshold of non-fatal results) →
       moderate backoff: ``batch_size -= batch_size_step``, ``delay += delay_step_sec``.
    3. **Fatal errors** (INVALID_KEY, NO_ACCESS, NO_QUOTA, NO_MODEL) → ignored
       (problem of specific key, not provider).
    4. **Success** → ramp-up: ``batch_size += step``, ``delay -= step``.
       After ``recovery_threshold`` consecutive successes, the step multiplier
       doubles for faster recovery.
    """

    # Start values for the adaptive controller (moved from HealthPolicyConfig).
    # The controller begins with these values and adjusts them within [min, max] bounds.
    start_batch_size: int = Field(default=30, gt=0)
    start_batch_delay_sec: float = Field(default=15.0, ge=0)

    # Boundaries — batch size
    min_batch_size: int = Field(default=5, gt=0)
    max_batch_size: int = Field(default=50, gt=0)

    # Boundaries — delay
    min_batch_delay_sec: float = Field(default=3.0, gt=0)
    max_batch_delay_sec: float = Field(default=120.0, gt=0)

    # Additive step sizes
    batch_size_step: int = Field(default=5, gt=0)
    delay_step_sec: float = Field(default=2.0, gt=0)

    # Aggressive reaction to rate-limit (multiplicative)
    rate_limit_divisor: int = Field(default=2, gt=1)
    rate_limit_delay_multiplier: float = Field(default=2.0, gt=1.0)

    # Recovery tuning
    recovery_threshold: int = Field(default=5, gt=0)
    recovery_step_multiplier: float = Field(default=2.0, gt=1.0)

    # Threshold for moderate backoff on transient errors
    failure_rate_threshold: float = Field(default=0.3, gt=0.0, lt=1.0)

    @model_validator(mode="after")
    def check_bounds(self) -> "AdaptiveBatchingConfig":
        """Validate that min bounds are strictly less than max bounds,
        and that start values are within [min, max]."""
        if self.min_batch_size >= self.max_batch_size:
            raise ValueError(
                f"min_batch_size ({self.min_batch_size}) must be < "
                f"max_batch_size ({self.max_batch_size})"
            )
        if self.min_batch_delay_sec >= self.max_batch_delay_sec:
            raise ValueError(
                f"min_batch_delay_sec ({self.min_batch_delay_sec}) must be < "
                f"max_batch_delay_sec ({self.max_batch_delay_sec})"
            )
        if not (self.min_batch_size <= self.start_batch_size <= self.max_batch_size):
            raise ValueError(
                f"start_batch_size ({self.start_batch_size}) must be in "
                f"[{self.min_batch_size}, {self.max_batch_size}]"
            )
        if not (
            self.min_batch_delay_sec
            <= self.start_batch_delay_sec
            <= self.max_batch_delay_sec
        ):
            raise ValueError(
                f"start_batch_delay_sec ({self.start_batch_delay_sec}) must be in "
                f"[{self.min_batch_delay_sec}, {self.max_batch_delay_sec}]"
            )
        return self

    def to_params(self) -> AdaptiveBatchingParams:
        """Convert this Pydantic model to a pure ``AdaptiveBatchingParams`` dataclass.

        Returns:
            A frozen dataclass with the same 13 field values, suitable for
            passing into ``AdaptiveBatchController`` without dragging the
            Pydantic dependency into the core layer.
        """
        return AdaptiveBatchingParams(
            start_batch_size=self.start_batch_size,
            start_batch_delay_sec=self.start_batch_delay_sec,
            min_batch_size=self.min_batch_size,
            max_batch_size=self.max_batch_size,
            min_batch_delay_sec=self.min_batch_delay_sec,
            max_batch_delay_sec=self.max_batch_delay_sec,
            batch_size_step=self.batch_size_step,
            delay_step_sec=self.delay_step_sec,
            rate_limit_divisor=self.rate_limit_divisor,
            rate_limit_delay_multiplier=self.rate_limit_delay_multiplier,
            recovery_threshold=self.recovery_threshold,
            recovery_step_multiplier=self.recovery_step_multiplier,
            failure_rate_threshold=self.failure_rate_threshold,
        )


class HealthPolicyConfig(BaseModel):
    """
    Defines the policy for the background worker's health checks.
    The fields are ordered by the magnitude of their time units for clarity.
    """

    model_config = ConfigDict(extra="forbid")

    # --- Intervals in Minutes (for short-term, recoverable errors) ---
    on_server_error_min: int = Field(default=30, gt=0)
    on_overload_min: int = Field(default=30, gt=0)

    # --- Intervals in Hours (for medium-term issues) ---
    on_other_error_hr: int = Field(default=1, gt=0)
    on_success_hr: int = Field(default=24, gt=0)
    on_rate_limit_hr: int = Field(default=1, gt=0)
    on_no_quota_hr: int = Field(default=6, gt=0)

    # --- Intervals in Days (for long-term, persistent errors) ---
    on_invalid_key_days: int = Field(default=10, gt=0)
    on_no_access_days: int = Field(default=10, gt=0)

    # --- Quarantine Policies (for managing chronically failing keys) ---
    # How many days a key must be failing continuously before it is put into quarantine.
    quarantine_after_days: int = Field(default=30, gt=0)
    # How often (in days) to re-check a key that is in quarantine.
    quarantine_recheck_interval_days: int = Field(default=10, gt=0)
    # After how many days of continuous failure to stop checking the key altogether.
    stop_checking_after_days: int = Field(default=90, gt=0)

    # --- Downtime Amnesty Policy ---
    # If a check is performed later than its scheduled time by more than this threshold,
    # the system assumes it was due to a downtime and resets the 'failing_since' counter.
    amnesty_threshold_days: float = Field(default=2.0, gt=0)

    # --- Batching Configuration (for controlling check request throughput) ---
    # Adaptive batch controller configuration. Uses default_factory to ensure
    # a valid config always exists even if the user omits the section.
    # Start values for batch_size and batch_delay now live inside
    # AdaptiveBatchingConfig (start_batch_size, start_batch_delay_sec).
    adaptive_batching: AdaptiveBatchingConfig = Field(
        default_factory=AdaptiveBatchingConfig
    )
    # Maximum time in seconds a single probe task is allowed to run before being force-cancelled.
    # This prevents "zombie" tasks from hanging indefinitely and blocking the dispatcher.
    task_timeout_sec: int = Field(default=900, gt=0)  # 15 minutes

    # --- Verification Loop Configuration (for retryable errors) ---
    # How many times to re-verify a key after a retryable error (e.g., rate limit).
    verification_attempts: int = Field(default=3, gt=0)
    # Hard delay between verification attempts (seconds). Should be >60 seconds to survive minute-based rate limits.
    verification_delay_sec: int = Field(default=65, ge=60)

    @model_validator(mode="after")
    def check_quarantine_logic(self) -> "HealthPolicyConfig":
        """Enforce quarantine_after_days <= stop_checking_after_days."""
        if self.quarantine_after_days > self.stop_checking_after_days:
            raise ValueError(
                f"quarantine_after_days ({self.quarantine_after_days}) cannot be greater than "
                f"stop_checking_after_days ({self.stop_checking_after_days})"
            )
        return self

    @model_validator(mode="after")
    def check_verification_timeout(self) -> "HealthPolicyConfig":
        """Validate task_timeout_sec is sufficient for verification loop to complete."""
        required_time = self.verification_attempts * self.verification_delay_sec * 2
        if self.task_timeout_sec < required_time:
            raise ValueError(
                f"task_timeout_sec ({self.task_timeout_sec}) is too low for "
                f"verification_attempts ({self.verification_attempts}) × "
                f"verification_delay_sec ({self.verification_delay_sec}) × 2 = {required_time}. "
                "Increase task_timeout_sec or reduce verification attempts / delay."
            )
        return self

    @model_validator(mode="after")
    def check_quarantine_recheck(self) -> "HealthPolicyConfig":
        """Validate quarantine_recheck_interval_days < stop_checking_after_days."""
        if self.quarantine_recheck_interval_days >= self.stop_checking_after_days:
            raise ValueError(
                f"quarantine_recheck_interval_days ({self.quarantine_recheck_interval_days}) "
                f"must be less than stop_checking_after_days ({self.stop_checking_after_days})"
            )
        return self


class ProxyConfig(BaseModel):
    """
    Configuration for using proxies with API requests.
    """

    # 'none': Direct connection.
    # 'static': Use a single, fixed proxy URL.
    # 'stealth': Use a rotating pool of proxies from a file/directory.
    mode: ProxyMode = ProxyMode.NONE
    # The URL for the proxy if mode is 'static' (e.g., "http://user:pass@host:port").
    static_url: str | None = None
    # Path to the directory containing proxy list files if mode is 'stealth'.
    pool_list_path: str | None = None

    @model_validator(mode="after")
    def validate_proxy_requirements(self) -> "ProxyConfig":
        """Validate proxy configuration based on mode."""
        if self.mode == "static" and not self.static_url:
            raise ValueError("Proxy mode is 'static' but 'static_url' is not set.")
        if self.mode == "stealth" and not self.pool_list_path:
            raise ValueError("Proxy mode is 'stealth' but 'pool_list_path' is not set.")
        return self


class TimeoutConfig(BaseModel):
    """
    Defines granular timeout settings for httpx requests. All values are in seconds.
    """

    # Timeout for establishing a connection.
    connect: float = Field(default=15.0, gt=0)
    # Timeout for waiting for a chunk of the response.
    read: float = Field(default=300.0, gt=0)
    # Timeout for sending a chunk of the request.
    write: float = Field(default=35.0, gt=0)
    # Timeout for acquiring a connection from the connection pool.
    pool: float = Field(default=35.0, gt=0)


class ErrorParsingRule(BaseModel):
    """
    Rule for parsing specific errors from response body.

    This allows fine-grained error classification based on response content,
    enabling the gateway to distinguish between different types of errors
    with the same HTTP status code (e.g., 400 Bad Request with different error types).
    """

    # HTTP status code this rule applies to (e.g., 400, 429, etc.)
    status_code: int = Field(..., ge=400, lt=600)

    # JSON path to the error field (e.g., "error.type", "error.code", "error.message").
    # Special values "$" and "" enable fulltext search mode — regex is applied against
    # the entire raw response body instead of a specific JSON field.
    error_path: str

    # Regular expression or exact value to match in the error field
    match_pattern: str

    # ErrorReason value to map to when this rule matches (e.g., "invalid_key", "no_quota")
    map_to: ErrorReason

    # Priority for rule matching (higher priority rules are checked first)
    priority: int = Field(default=0, ge=0)

    # Human-readable description of what this rule detects
    description: str = ""

    @field_validator("match_pattern")
    @classmethod
    def validate_match_pattern(cls, v: str) -> str:
        """Validate that match_pattern is a compilable regex."""
        try:
            re.compile(v)
        except re.error as e:
            raise ValueError(
                f"match_pattern '{v}' is not a valid regular expression: {e}"
            ) from e
        return v


class ErrorParsingConfig(BaseModel):
    """
    Configuration for error response parsing in the gateway.

    This enables the gateway to analyze error response bodies and refine
    error classification beyond simple HTTP status codes. This is particularly
    useful for providers that return detailed error information in the response body.
    """

    # Whether error parsing is enabled for this provider
    enabled: bool = False

    # List of error parsing rules to apply
    rules: list[ErrorParsingRule] = Field(default_factory=list)

    @model_validator(mode="after")
    def check_unique_priorities(self) -> "ErrorParsingConfig":
        """Validate that priorities are unique within each status_code group."""
        status_priorities: dict[int, set[int]] = {}
        for rule in self.rules:
            status_priorities.setdefault(rule.status_code, set())
            if rule.priority in status_priorities[rule.status_code]:
                raise ValueError(
                    f"Duplicate priority {rule.priority} for status_code "
                    f"{rule.status_code} in error parsing rules. "
                    "Each rule within the same status_code must have a unique priority."
                )
            status_priorities[rule.status_code].add(rule.priority)
        return self


class GatewayPolicyConfig(BaseModel):
    """Groups all policies applied by the API Gateway during live request processing."""

    model_config = ConfigDict(extra="forbid")

    # Controls whether streaming is enabled for this provider instance.
    # See src.core.constants.StreamingMode for allowed values.
    streaming_mode: StreamingMode = StreamingMode.AUTO

    # Controls the debug logging mode for this provider instance.
    # See src.core.constants.DebugMode for allowed values.
    debug_mode: DebugMode = DebugMode.DISABLED

    # Policy for automatically retrying failed requests.
    retry: RetryPolicyConfig = Field(default_factory=RetryPolicyConfig)
    # Policy for the circuit breaker to handle endpoint failures.
    circuit_breaker: CircuitBreakerConfig = Field(default_factory=CircuitBreakerConfig)


class KeyInventoryConfig(BaseModel):
    """
    Configuration for periodic key inventory export by status.

    Controls exporting keys grouped by their status into separate NDJSON files.
    Each status in ``statuses`` produces a subdirectory with keys of that status.
    """

    model_config = ConfigDict(extra="forbid")

    # Whether inventory export is enabled for this provider.
    enabled: bool = False
    # Interval in minutes between inventory export cycles. Must be > 0.
    interval_minutes: int = Field(default=1440, gt=0)
    # List of statuses to export as separate inventory groups.
    statuses: list[Status] = []


class KeyExportConfig(BaseModel):
    """
    Configuration for key export features: snapshots, inventory, and raw cleanup.

    Controls all key export operations for a single provider instance, including
    periodic full snapshots, status-based inventory exports, and safe cleanup of
    raw key files after successful synchronization.
    """

    model_config = ConfigDict(extra="forbid")

    # Master switch: if False, no export operations run for this provider.
    enabled: bool = False
    # If True, raw key files are safely removed after successful DB sync.
    clean_raw_after_sync: bool = True
    # Interval in hours between full snapshot exports. 0 disables snapshots.
    snapshot_interval_hours: int = Field(default=0, ge=0)
    # Inventory export configuration (status-based grouping).
    inventory: KeyInventoryConfig = Field(default_factory=KeyInventoryConfig)


class ProviderConfig(BaseModel):
    """
    Configuration for a single, named LLM provider instance.
    This is the core component of the provider configuration, aligning with Step 4 of the plan.
    """

    model_config = ConfigDict(extra="forbid")

    # The type of the provider, used to look up templates (e.g., 'gemini', 'deepseek').
    provider_type: ProviderType
    # A flag to enable or disable this entire provider instance.
    enabled: bool = True
    # The base URL for the provider's API.
    api_base_url: str = ""
    # The default model to use for this instance if not specified in the request.
    default_model: str = ""
    # If true, all keys for this provider share the same status (e.g., for APIs with account-level rate limits).
    shared_key_status: bool = False

    # If True, the instance gets a dedicated httpx.AsyncClient (separate connection pool).
    # Useful for high-load instances (e.g., litellm with agents) so their
    # TCP connections do not starve connections from other providers in the shared client.
    # Defaults to False — a shared client is used with other providers of the same proxy mode.
    dedicated_http_client: bool = False

    # A dictionary mapping model names to their detailed configurations.
    # This structure is flexible and supports multiple model types under one provider.
    # It correctly uses default_factory to prevent mutable default issues.
    models: dict[str, ModelInfo] = Field(default_factory=dict)

    # --- Nested Configuration Objects ---
    # These fields are intentionally not Optional. By using default_factory, we ensure
    # that a default-configured object always exists, even if the section is completely
    # omitted from the user's YAML file. This is the key to the new design and
    # directly implements the user's requirement for "optional sections".
    access_control: AccessControlConfig = Field(default_factory=AccessControlConfig)
    proxy_config: ProxyConfig = Field(default_factory=ProxyConfig)
    timeouts: TimeoutConfig = Field(default_factory=TimeoutConfig)
    error_parsing: ErrorParsingConfig = Field(default_factory=ErrorParsingConfig)
    worker_health_policy: HealthPolicyConfig = Field(default_factory=HealthPolicyConfig)
    key_export: KeyExportConfig = Field(default_factory=KeyExportConfig)
    gateway_policy: GatewayPolicyConfig = Field(default_factory=GatewayPolicyConfig)


# ==============================================================================
# 3. GLOBAL CONFIGURATION CLASSES
# ==============================================================================
# This follows Step 5 of the plan, defining the top-level configuration sections
# that are not specific to any single provider.


class DatabaseRetryConfig(BaseModel):
    """
    Retry settings for transient database errors.

    Defines the retry policy for temporary DB connection failures
    (connection drop, protocol error, pool exhaustion, deadlock).
    """

    # Maximum number of attempts (including the first). Capped at 10 to prevent
    # infinite retry.
    max_attempts: int = Field(default=3, gt=0, le=10)
    # Base delay before the first retry attempt (seconds).
    base_delay_sec: float = Field(default=1.0, gt=0)
    # Multiplier for exponential backoff: delay = base * factor^(attempt).
    # A value of 1.0 yields linear backoff.
    backoff_factor: float = Field(default=2.0, ge=1.0)
    # Adds a random multiplier [0.5, 1.5] to the delay to prevent
    # thundering herd when multiple operations recover simultaneously.
    jitter: bool = True


class DatabasePoolConfig(BaseModel):
    """
    PostgreSQL connection pool settings.

    Defines the minimum and maximum size of the async connection pool
    used by ``asyncpg.create_pool()``.
    """

    # Minimum number of connections in the pool.
    min_size: int = Field(default=1, gt=0)
    # Maximum number of connections in the pool.
    max_size: int = Field(default=15, gt=0)

    @model_validator(mode="after")
    def check_bounds(self) -> "DatabasePoolConfig":
        """Validate: minimum pool size must not exceed maximum."""
        if self.min_size > self.max_size:
            raise ValueError(
                f"min_size ({self.min_size}) must be <= max_size ({self.max_size})"
            )
        return self


class DatabaseConfig(BaseModel):
    """
    Configuration for the PostgreSQL database connection.
    """

    host: str = "localhost"
    port: int = Field(default=5432, gt=0, lt=65536)
    user: str = "llm_gateway"
    # This should be loaded from an environment variable, e.g., "${DB_PASSWORD}".
    password: str = ""
    dbname: str = "llmgateway"
    # Retry settings for transient DB errors.
    retry: DatabaseRetryConfig = Field(default_factory=DatabaseRetryConfig)
    # PostgreSQL connection pool settings.
    pool: DatabasePoolConfig = Field(default_factory=DatabasePoolConfig)

    def to_dsn(self) -> str:
        """
        Constructs a PostgreSQL Data Source Name (DSN) string from the config.
        This is a value-add method as planned in the "Improvements" section.
        """
        if not self.password:
            raise ValueError("Database password is not set. Cannot construct DSN.")
        return f"postgresql://{self.user}:{self.password}@{self.host}:{self.port}/{self.dbname}"


class WorkerConfig(BaseModel):
    """Global settings specifically for the background worker service."""

    # The maximum number of provider instances to check concurrently.
    max_concurrent_providers: int = Field(default=10, gt=0)


class LoggingConfig(BaseModel):
    """
    Global configuration for application logging.
    """

    # The global log level for the application. Can be "DEBUG", "INFO", "WARNING", "ERROR".
    level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"


class GatewayConfig(BaseModel):
    """
    API Gateway (Conductor) settings.

    Defines the host, port, and number of uvicorn workers for the FastAPI application.
    CLI arguments ``--host``, ``--port``, ``--workers`` override these values
    if explicitly passed at startup.
    """

    model_config = ConfigDict(extra="forbid")

    # Host the gateway listens on.
    host: str = "0.0.0.0"
    # Port the gateway listens on.
    port: int = Field(default=55300, gt=0, lt=65536)
    # Number of uvicorn worker processes.
    workers: int = Field(default=4, gt=0, le=64)


# ==============================================================================
# 4. ROOT CONFIGURATION OBJECT
# ==============================================================================
# This is the final step of the plan (Step 6), the top-level class that holds
# the entire application's configuration.


class Config(BaseModel):
    """
    The main configuration object for the entire llmGateway application.
    It serves as the root of the configuration tree.
    """

    model_config = ConfigDict(extra="forbid")

    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    worker: WorkerConfig = Field(default_factory=WorkerConfig)
    metrics: MetricsConfig = Field(default_factory=MetricsConfig)
    gateway: GatewayConfig = Field(default_factory=GatewayConfig)
    # A dictionary mapping the unique instance name to its full configuration.
    providers: dict[str, ProviderConfig] = Field(default_factory=dict)

    @model_validator(mode="after")
    def check_unique_tokens(self) -> "Config":
        """Ensure global uniqueness of gateway_access_token across all enabled providers."""
        used_tokens: set[str] = set()
        for name, provider in self.providers.items():
            if not provider.enabled:
                continue
            token = provider.access_control.gateway_access_token
            if not token:
                continue  # Will be caught by ProviderConfig validation if required
            if token in used_tokens:
                raise ValueError(
                    f"Duplicate gateway_access_token found in provider '{name}'. "
                    "Tokens must be unique across all enabled providers."
                )
            used_tokens.add(token)
        return self

    @model_validator(mode="after")
    def validate_provider_names(self) -> "Config":
        """Ensure provider instance names are filesystem-safe (alphanumeric, hyphens, underscores only)."""
        pattern = re.compile(r"^[a-zA-Z0-9_-]+$")
        for name in self.providers:
            if not pattern.match(name):
                raise ValueError(
                    f"Provider instance name '{name}' is not filesystem-safe. "
                    "Must match ^[a-zA-Z0-9_-]+$ (alphanumeric, hyphens, underscores only)."
                )
        return self
