#!/usr/bin/env python3

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

# Import core enums for type hints and validation in schemas.
# Pydantic will automatically validate enum values at runtime.

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
    attempts: int = 0
    # Initial delay in seconds before the first retry.
    backoff_sec: float = 0.1
    # Multiplier for the delay for subsequent retries (e.g., 2.0 for exponential backoff).
    backoff_factor: float = 1.5


class RetryPolicyConfig(BaseModel):
    """Container for the gateway's request retry policies."""

    enabled: bool = False
    # Specific retry settings for when a key is invalid, out of quota, etc.
    on_key_error: RetryOnErrorConfig = Field(default_factory=RetryOnErrorConfig)
    # Specific retry settings for 5xx server-side errors.
    on_server_error: RetryOnErrorConfig = Field(default_factory=RetryOnErrorConfig)


class BackoffConfig(BaseModel):
    """Configuration for the exponential backoff strategy of the circuit breaker."""

    # The initial duration in seconds to wait after the circuit opens.
    base_duration_sec: int = 30
    # The maximum duration the backoff can reach.
    max_duration_sec: int = 1800
    # The factor by which the duration increases after each failed check.
    factor: float = 2.0


class CircuitBreakerConfig(BaseModel):
    """
    Configuration for the Circuit Breaker mechanism to prevent cascading failures.
    """

    enabled: bool = False
    # 'auto_recovery' will periodically re-test the endpoint.
    # 'manual_reset' requires external intervention to close the circuit.
    mode: str = "auto_recovery"
    # The number of consecutive failures required to open the circuit.
    failure_threshold: int = 10
    # Configuration for the backoff strategy when the circuit is open.
    backoff: BackoffConfig = Field(default_factory=BackoffConfig)
    # A random delay added to backoff to prevent thundering herd problems.
    jitter_sec: int = 5


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

    # Стартовые значения для адаптивного контроллера (перенесены из HealthPolicyConfig).
    # Контроллер начинает с этих значений и подстраивает их в границах [min, max].
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
    # Стартовые значения batch_size и batch_delay теперь находятся внутри
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

    # --- Fast Status Mapping (for worker health checks) ---
    # Mapping of HTTP status codes to ErrorReason strings for fast, body-less error handling.
    # When a status code matches an entry here, the worker will IMMEDIATELY fail the check
    # with the mapped reason without reading the response body.
    fast_status_mapping: dict[int, str] = Field(
        default_factory=dict,
        description="Mapping of HTTP status codes to ErrorReason strings",
    )

    @model_validator(mode="after")
    def check_quarantine_logic(self) -> "HealthPolicyConfig":
        """Enforce quarantine_after_days <= stop_checking_after_days."""
        if self.quarantine_after_days > self.stop_checking_after_days:
            raise ValueError(
                f"quarantine_after_days ({self.quarantine_after_days}) cannot be greater than "
                f"stop_checking_after_days ({self.stop_checking_after_days})"
            )
        return self


class ProxyConfig(BaseModel):
    """
    Configuration for using proxies with API requests.
    """

    # 'none': Direct connection.
    # 'static': Use a single, fixed proxy URL.
    # 'stealth': Use a rotating pool of proxies from a file/directory.
    mode: str = "none"
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

    # JSON path to the error field (e.g., "error.type", "error.code", "error.message")
    error_path: str

    # Regular expression or exact value to match in the error field
    match_pattern: str

    # ErrorReason value to map to when this rule matches (e.g., "invalid_key", "no_quota")
    map_to: str

    # Priority for rule matching (higher priority rules are checked first)
    priority: int = Field(default=0, ge=0)

    # Human-readable description of what this rule detects
    description: str = ""


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


class GatewayPolicyConfig(BaseModel):
    """Groups all policies applied by the API Gateway during live request processing."""

    # Controls whether streaming is enabled for this provider instance.
    # See src.core.constants.StreamingMode for allowed values.
    streaming_mode: Literal["auto", "disabled"] = "auto"

    # Controls the debug logging mode for this provider instance.
    # See src.core.constants.DebugMode for allowed values.
    debug_mode: Literal["disabled", "no_content", "full_body"] = "disabled"

    # Configuration for parsing error responses to refine error classification
    # This enables distinguishing between different error types with the same HTTP status code
    error_parsing: ErrorParsingConfig = Field(default_factory=ErrorParsingConfig)

    # Policy for automatically retrying failed requests.
    retry: RetryPolicyConfig = Field(default_factory=RetryPolicyConfig)
    # Policy for the circuit breaker to handle endpoint failures.
    circuit_breaker: CircuitBreakerConfig = Field(default_factory=CircuitBreakerConfig)

    # Mapping of HTTP status codes to ErrorReason strings for fast, body-less error handling.
    # When a status code matches an entry here, the gateway will IMMEDIATELY fail the request
    # with the mapped reason without reading the response body.
    # WARNING: This prevents forwarding specific upstream error messages to the client.
    fast_status_mapping: dict[int, str] = Field(default_factory=dict)


class ProviderConfig(BaseModel):
    """
    Configuration for a single, named LLM provider instance.
    This is the core component of the provider configuration, aligning with Step 4 of the plan.
    """

    model_config = ConfigDict(extra="forbid")

    # The type of the provider, used to look up templates (e.g., 'gemini', 'deepseek').
    provider_type: str
    # A flag to enable or disable this entire provider instance.
    enabled: bool = True
    # Path to the directory containing API key files for this instance.
    keys_path: str
    # The base URL for the provider's API.
    api_base_url: str = ""
    # The default model to use for this instance if not specified in the request.
    default_model: str = ""
    # If true, all keys for this provider share the same status (e.g., for APIs with account-level rate limits).
    shared_key_status: bool = False

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
    worker_health_policy: HealthPolicyConfig = Field(default_factory=HealthPolicyConfig)
    proxy_config: ProxyConfig = Field(default_factory=ProxyConfig)
    timeouts: TimeoutConfig = Field(default_factory=TimeoutConfig)
    gateway_policy: GatewayPolicyConfig = Field(default_factory=GatewayPolicyConfig)


# ==============================================================================
# 3. GLOBAL CONFIGURATION CLASSES
# ==============================================================================
# This follows Step 5 of the plan, defining the top-level configuration sections
# that are not specific to any single provider.


class DatabaseRetryConfig(BaseModel):
    """
    Настройки retry для transient-ошибок базы данных.

    Определяет политику повторных попыток при временных сбоях соединения с БД
    (разрыв соединения, ошибка протокола, исчерпание пула, deadlock).
    """

    # Максимальное число попыток (включая первую). Ограничено 10 для предотвращения
    # бесконечного retry.
    max_attempts: int = Field(default=3, gt=0, le=10)
    # Базовая задержка перед первой повторной попыткой (секунды).
    base_delay_sec: float = Field(default=1.0, gt=0)
    # Множитель для экспоненциального backoff: delay = base * factor^(attempt).
    # Значение 1.0 даёт линейный backoff.
    backoff_factor: float = Field(default=2.0, ge=1.0)
    # Добавляет случайный множитель [0.5, 1.5] к задержке для предотвращения
    # thundering herd при одновременном восстановлении нескольких операций.
    jitter: bool = True


class DatabaseConfig(BaseModel):
    """
    Configuration for the PostgreSQL database connection.
    """

    host: str = "localhost"
    port: int = Field(default=5432, gt=0)
    user: str = "llm_gateway"
    # This should be loaded from an environment variable, e.g., "${DB_PASSWORD}".
    password: str = ""
    dbname: str = "llmgateway"
    # Настройки retry для transient-ошибок БД.
    retry: DatabaseRetryConfig = Field(default_factory=DatabaseRetryConfig)

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
