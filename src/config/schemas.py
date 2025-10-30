#!/usr/bin/env python3

from dataclasses import dataclass, field
from typing import Dict, Any, Optional

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
    test_payload: Dict[str, Any] = field(default_factory=dict)


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
    backoff_sec: float = 1.0
    # Multiplier for the delay for subsequent retries (e.g., 2.0 for exponential backoff).
    backoff_factor: float = 2.0


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
    mode: str = 'auto_recovery'
    # The number of consecutive failures required to open the circuit.
    failure_threshold: int = 10
    # Configuration for the backoff strategy when the circuit is open.
    backoff: BackoffConfig = field(default_factory=BackoffConfig)
    # A random delay added to backoff to prevent thundering herd problems.
    jitter_sec: int = 5


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
    static_url: Optional[str] = None
    # Path to the directory containing proxy list files if mode is 'stealth'.
    pool_list_path: Optional[str] = None


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
class GatewayPolicyConfig:
    """Groups all policies applied by the API Gateway during live request processing."""
    # Policy for automatically retrying failed requests.
    retry: RetryPolicyConfig = field(default_factory=RetryPolicyConfig)
    # Policy for the circuit breaker to handle endpoint failures.
    circuit_breaker: CircuitBreakerConfig = field(default_factory=CircuitBreakerConfig)


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
    models: Dict[str, ModelInfo] = field(default_factory=dict)

    # --- Nested Configuration Objects ---
    # These fields are intentionally not Optional. By using default_factory, we ensure
    # that a default-configured object always exists, even if the section is completely
    # omitted from the user's YAML file. This is the key to the new design and
    # directly implements the user's requirement for "optional sections".
    access_control: AccessControlConfig = field(default_factory=AccessControlConfig)
    health_policy: HealthPolicyConfig = field(default_factory=HealthPolicyConfig)
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
    Global configuration for the statistics and summary logging system.
    """
    # Path to the directory for summary log files.
    summary_log_path: str = "logs/summary/"
    # Interval in minutes for writing a summary log.
    summary_interval_min: int = 30
    # Maximum size in MB for a single summary log file before rotation.
    summary_log_max_size_mb: int = 5
    # Number of backup summary log files to keep.
    summary_log_backup_count: int = 3


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
    debug: bool = False
    database: DatabaseConfig = field(default_factory=DatabaseConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    worker: WorkerConfig = field(default_factory=WorkerConfig)
    # A dictionary mapping the unique instance name to its full configuration.
    providers: Dict[str, ProviderConfig] = field(default_factory=dict)

