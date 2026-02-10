#!/usr/bin/env python3

from dataclasses import dataclass, field
from typing import Any, Literal

# Import core enums for type hints in schemas.
# This improves IDE support and documentation clarity,
# even though runtime validation is performed by the ConfigValidator.

# ==============================================================================
# 1. ATOMIC AND NESTED CONFIGURATION CLASSES
# ==============================================================================
# This follows Step 1 and 2 of the plan: define the smallest building blocks first.
# These will be nested within larger configuration objects.


@dataclass
class ModelInfo:
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
    test_payload: dict[str, Any] = field(default_factory=dict)  # type: ignore


@dataclass
class AccessControlConfig:
    """
    Configuration for gateway access control for a specific provider instance.
    """

    # The token that client applications must provide in the Authorization header
    # to use this specific provider instance through the gateway.
    gateway_access_token: str = ""


@dataclass
class RetryOnErrorConfig:
    """Defines retry behavior for a specific error category (e.g., server errors)."""

    # Number of retry attempts for this error type. 0 means no retries.
    attempts: int = 0
    # Initial delay in seconds before the first retry.
    backoff_sec: float = 0.1
    # Multiplier for the delay for subsequent retries (e.g., 2.0 for exponential backoff).
    backoff_factor: float = 1.5


@dataclass
class RetryPolicyConfig:
    """Container for the gateway's request retry policies."""

    enabled: bool = False
    # Specific retry settings for when a key is invalid, out of quota, etc.
    on_key_error: RetryOnErrorConfig = field(default_factory=RetryOnErrorConfig)
    # Specific retry settings for 5xx server-side errors.
    on_server_error: RetryOnErrorConfig = field(default_factory=RetryOnErrorConfig)


@dataclass
class BackoffConfig:
    """Configuration for the exponential backoff strategy of the circuit breaker."""

    # The initial duration in seconds to wait after the circuit opens.
    base_duration_sec: int = 30
    # The maximum duration the backoff can reach.
    max_duration_sec: int = 1800
    # The factor by which the duration increases after each failed check.
    factor: float = 2.0


@dataclass
class CircuitBreakerConfig:
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
    backoff: BackoffConfig = field(default_factory=BackoffConfig)
    # A random delay added to backoff to prevent thundering herd problems.
    jitter_sec: int = 5


@dataclass
class MetricsConfig:
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


@dataclass
class HealthPolicyConfig:
    """
    Defines the policy for the background worker's health checks.
    The fields are ordered by the magnitude of their time units for clarity.
    """

    # --- Intervals in Minutes (for short-term, recoverable errors) ---
    on_server_error_min: int = 30
    on_overload_min: int = 60

    # --- Intervals in Hours (for medium-term issues) ---
    on_other_error_hr: int = 1
    on_success_hr: int = 1
    on_rate_limit_hr: int = 4
    on_no_quota_hr: int = 4

    # --- Intervals in Days (for long-term, persistent errors) ---
    on_invalid_key_days: int = 10
    on_no_access_days: int = 10

    # --- Quarantine Policies (for managing chronically failing keys) ---
    # How many days a key must be failing continuously before it is put into quarantine.
    quarantine_after_days: int = 30
    # How often (in days) to re-check a key that is in quarantine.
    quarantine_recheck_interval_days: int = 10
    # After how many days of continuous failure to stop checking the key altogether.
    stop_checking_after_days: int = 90

    # --- Batching Configuration (for controlling check request throughput) ---
    # How many keys to check in a single batch for this provider.
    batch_size: int = 30
    # Delay in seconds between batches to avoid overwhelming the API.
    batch_delay_sec: int = 15

    # --- Verification Loop Configuration (for retryable errors) ---
    # How many times to re-verify a key after a retryable error (e.g., rate limit).
    verification_attempts: int = 3
    # Hard delay between verification attempts (seconds). Should be >60 seconds to survive minute-based rate limits.
    verification_delay_sec: int = 65

    # --- Fast Status Mapping (for worker health checks) ---
    # Mapping of HTTP status codes to ErrorReason strings for fast, body-less error handling.
    # When a status code matches an entry here, the worker will IMMEDIATELY fail the check
    # with the mapped reason without reading the response body.
    fast_status_mapping: dict[int, str] = field(default_factory=dict)  # type: ignore


@dataclass
class ProxyConfig:
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


@dataclass
class TimeoutConfig:
    """
    Defines granular timeout settings for httpx requests. All values are in seconds.
    """

    # Timeout for establishing a connection.
    connect: float = 5.0
    # Timeout for waiting for a chunk of the response.
    read: float = 20.0
    # Timeout for sending a chunk of the request.
    write: float = 10.0
    # Timeout for acquiring a connection from the connection pool.
    pool: float = 5.0


@dataclass
class ErrorParsingRule:
    """
    Rule for parsing specific errors from response body.

    This allows fine-grained error classification based on response content,
    enabling the gateway to distinguish between different types of errors
    with the same HTTP status code (e.g., 400 Bad Request with different error types).
    """

    # HTTP status code this rule applies to (e.g., 400, 429, etc.)
    status_code: int

    # JSON path to the error field (e.g., "error.type", "error.code", "error.message")
    error_path: str

    # Regular expression or exact value to match in the error field
    match_pattern: str

    # ErrorReason value to map to when this rule matches (e.g., "invalid_key", "no_quota")
    map_to: str

    # Priority for rule matching (higher priority rules are checked first)
    priority: int = 0

    # Human-readable description of what this rule detects
    description: str = ""


@dataclass
class ErrorParsingConfig:
    """
    Configuration for error response parsing in the gateway.

    This enables the gateway to analyze error response bodies and refine
    error classification beyond simple HTTP status codes. This is particularly
    useful for providers that return detailed error information in the response body.
    """

    # Whether error parsing is enabled for this provider
    enabled: bool = False

    # List of error parsing rules to apply
    rules: list[ErrorParsingRule] = field(default_factory=list)  # type: ignore


@dataclass
class GatewayPolicyConfig:
    """Groups all policies applied by the API Gateway during live request processing."""

    # Controls whether streaming is enabled for this provider instance.
    # See src.core.constants.StreamingMode for allowed values.
    streaming_mode: Literal["auto", "disabled"] = "auto"

    # Controls the debug logging mode for this provider instance.
    # See src.core.constants.DebugMode for allowed values.
    debug_mode: Literal["disabled", "headers_only", "full_body"] = "disabled"

    # Configuration for parsing error responses to refine error classification
    # This enables distinguishing between different error types with the same HTTP status code
    error_parsing: ErrorParsingConfig = field(default_factory=ErrorParsingConfig)

    # Policy for automatically retrying failed requests.
    retry: RetryPolicyConfig = field(default_factory=RetryPolicyConfig)
    # Policy for the circuit breaker to handle endpoint failures.
    circuit_breaker: CircuitBreakerConfig = field(default_factory=CircuitBreakerConfig)

    # Mapping of HTTP status codes to ErrorReason strings for fast, body-less error handling.
    # When a status code matches an entry here, the gateway will IMMEDIATELY fail the request
    # with the mapped reason without reading the response body.
    # WARNING: This prevents forwarding specific upstream error messages to the client.
    fast_status_mapping: dict[int, str] = field(default_factory=dict)  # type: ignore


@dataclass
class ProviderConfig:
    """
    Configuration for a single, named LLM provider instance.
    This is the core component of the provider configuration, aligning with Step 4 of the plan.
    """

    # The type of the provider, used to look up templates (e.g., 'gemini', 'deepseek').
    provider_type: str = ""
    # A flag to enable or disable this entire provider instance.
    enabled: bool = True
    # Path to the directory containing API key files for this instance.
    keys_path: str = ""
    # The base URL for the provider's API.
    api_base_url: str = ""
    # The default model to use for this instance if not specified in the request.
    default_model: str = ""
    # If true, all keys for this provider share the same status (e.g., for APIs with account-level rate limits).
    shared_key_status: bool = False

    # A dictionary mapping model names to their detailed configurations.
    # This structure is flexible and supports multiple model types under one provider.
    # It correctly uses default_factory to prevent mutable default issues.
    models: dict[str, ModelInfo] = field(default_factory=dict)  # type: ignore

    # --- Nested Configuration Objects ---
    # These fields are intentionally not Optional. By using default_factory, we ensure
    # that a default-configured object always exists, even if the section is completely
    # omitted from the user's YAML file. This is the key to the new design and
    # directly implements the user's requirement for "optional sections".
    access_control: AccessControlConfig = field(default_factory=AccessControlConfig)
    worker_health_policy: HealthPolicyConfig = field(default_factory=HealthPolicyConfig)
    proxy_config: ProxyConfig = field(default_factory=ProxyConfig)
    timeouts: TimeoutConfig = field(default_factory=TimeoutConfig)
    gateway_policy: GatewayPolicyConfig = field(default_factory=GatewayPolicyConfig)


# ==============================================================================
# 3. GLOBAL CONFIGURATION CLASSES
# ==============================================================================
# This follows Step 5 of the plan, defining the top-level configuration sections
# that are not specific to any single provider.


@dataclass
class DatabaseConfig:
    """
    Configuration for the PostgreSQL database connection.
    """

    host: str = "localhost"
    port: int = 5433
    user: str = "llm_gateway"
    # This should be loaded from an environment variable, e.g., "${DB_PASSWORD}".
    password: str = ""
    dbname: str = "llmgateway"

    def to_dsn(self) -> str:
        """
        Constructs a PostgreSQL Data Source Name (DSN) string from the config.
        This is a value-add method as planned in the "Improvements" section.
        """
        if not self.password:
            raise ValueError("Database password is not set. Cannot construct DSN.")
        return f"postgresql://{self.user}:{self.password}@{self.host}:{self.port}/{self.dbname}"


@dataclass
class WorkerConfig:
    """Global settings specifically for the background worker service."""

    # The maximum number of provider instances to check concurrently.
    max_concurrent_providers: int = 10


@dataclass
class LoggingConfig:
    """
    Global configuration for application logging.
    """

    pass


# ==============================================================================
# 4. ROOT CONFIGURATION OBJECT
# ==============================================================================
# This is the final step of the plan (Step 6), the top-level class that holds
# the entire application's configuration.


@dataclass
class Config:
    """
    The main configuration object for the entire llmGateway application.
    It serves as the root of the configuration tree.
    """

    database: DatabaseConfig = field(default_factory=DatabaseConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    worker: WorkerConfig = field(default_factory=WorkerConfig)
    metrics: MetricsConfig = field(default_factory=MetricsConfig)
    # A dictionary mapping the unique instance name to its full configuration.
    providers: dict[str, ProviderConfig] = field(default_factory=dict)  # type: ignore
