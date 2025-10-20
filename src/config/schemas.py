# src/config/schemas.py

from dataclasses import dataclass, field
from typing import Dict, List, Optional

@dataclass
class AccessControlConfig:
    """
    Configuration for gateway access control for a specific provider instance.
    """
    gateway_access_token: str = ""

@dataclass
class HealthPolicyConfig:
    """
    Defines the policy for how and when to re-test API keys based on their status.
    This policy is primarily used by the background worker.
    All intervals are specified in the unit denoted by the field name.
    """
    on_success_hr: int = 2
    on_overload_min: int = 60
    on_no_quota_hr: int = 24
    on_rate_limit_min: int = 180
    on_server_error_min: int = 30
    on_invalid_key_days: int = 10
    on_other_error_hr: int = 1
    batch_size: int = 30
    batch_delay_sec: int = 15

@dataclass
class ProxyConfig:
    """
    Configuration for proxy usage, supporting multiple operational modes.
    """
    mode: str = "none"
    static_url: Optional[str] = None
    pool_list_path: Optional[str] = None

@dataclass
class TimeoutConfig:
    """
    Defines granular timeout settings for httpx requests.
    All values are in seconds.
    """
    connect: float = 5.0
    read: float = 20.0
    write: float = 10.0
    pool: float = 5.0

# --- NEW: Configuration for Retry Policy ---
@dataclass
class RetryOnErrorConfig:
    """Defines retry behavior for a specific error category."""
    # Number of retry attempts.
    attempts: int = 0
    # Initial delay in seconds before the first retry.
    backoff_sec: float = 1.0
    # Multiplier for exponential backoff (e.g., 2.0 for doubling the delay).
    backoff_factor: float = 2.0

@dataclass
class RetryPolicyConfig:
    """Container for the gateway's retry policies."""
    # Master switch to enable or disable the retry mechanism.
    enabled: bool = False
    # Policy for when an error is related to the API key (e.g., invalid, no quota).
    on_key_error: RetryOnErrorConfig = field(default_factory=RetryOnErrorConfig)
    # Policy for when an error is transient and server-related (e.g., timeout, 5xx error).
    on_server_error: RetryOnErrorConfig = field(default_factory=RetryOnErrorConfig)

# --- NEW: Configuration for Circuit Breaker ---
@dataclass
class BackoffConfig:
    """Configuration for the exponential backoff strategy of the circuit breaker."""
    # Initial duration in seconds to keep the circuit open.
    base_duration_sec: int = 30
    # Maximum duration to prevent excessively long waits.
    max_duration_sec: int = 1800  # 30 minutes
    # Multiplier for each subsequent opening of the circuit.
    factor: float = 2.0

@dataclass
class CircuitBreakerConfig:
    """Configuration for the circuit breaker mechanism."""
    # Master switch to enable or disable the circuit breaker.
    enabled: bool = False
    # Operating mode: 'auto_recovery' or 'manual_reset'.
    mode: str = 'auto_recovery'
    # Number of consecutive failures to trigger opening the circuit.
    failure_threshold: int = 10
    # Configuration for the backoff strategy.
    backoff: BackoffConfig = field(default_factory=BackoffConfig)
    # Maximum random "jitter" in seconds added to the open duration to prevent thundering herd.
    jitter_sec: int = 5

# --- NEW: Container for all Gateway-specific policies ---
@dataclass
class GatewayPolicyConfig:
    """Groups all policies applied by the API Gateway during request processing."""
    retry: RetryPolicyConfig = field(default_factory=RetryPolicyConfig)
    circuit_breaker: CircuitBreakerConfig = field(default_factory=CircuitBreakerConfig)

@dataclass
class ProviderConfig:
    """
    Configuration for a single LLM provider instance.
    """
    provider_type: str = ""
    enabled: bool = False
    keys_path: str = ""
    api_base_url: str = ""
    default_model: str = ""
    
    shared_key_status: bool = False
    
    models: Dict[str, List[str]] = field(default_factory=dict)
    
    access_control: AccessControlConfig = field(default_factory=AccessControlConfig)
    health_policy: HealthPolicyConfig = field(default_factory=HealthPolicyConfig)
    proxy_config: ProxyConfig = field(default_factory=ProxyConfig)
    timeouts: TimeoutConfig = field(default_factory=TimeoutConfig)

    # --- NEW FIELD ---
    # This clearly separates policies for the gateway from other settings.
    gateway_policy: GatewayPolicyConfig = field(default_factory=GatewayPolicyConfig)


@dataclass
class LoggingConfig:
    """
    Global configuration for the statistics and logging system.
    """
    summary_log_path: str = "logs/summary/"
    summary_interval_min: int = 60
    summary_log_max_size_mb: int = 5
    summary_log_backup_count: int = 3

@dataclass
class DatabaseConfig:
    """
    Configuration for the PostgreSQL database connection.
    It is strongly recommended to load 'user' and 'password' from environment variables.
    """
    host: str = "localhost"
    port: int = 5433
    user: str = "llm_gateway"
    password: str = ""
    dbname: str = "llmgateway"

    def to_dsn(self) -> str:
        """
        Constructs a PostgreSQL Data Source Name (DSN) string from the config.
        """
        return f"postgresql://{self.user}:{self.password}@{self.host}:{self.port}/{self.dbname}"

# --- NEW: Configuration for the Background Worker ---
@dataclass
class WorkerConfig:
    """Global settings specifically for the background worker service."""
    # Maximum number of providers to be processed concurrently by probes.
    max_concurrent_providers: int = 10

@dataclass
class Config:
    """
    The main configuration object for the entire application.
    """
    debug: bool = False
    database: DatabaseConfig = field(default_factory=DatabaseConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    providers: Dict[str, ProviderConfig] = field(default_factory=dict)
    
    # --- NEW FIELD ---
    # Centralizes worker-specific settings.
    worker: WorkerConfig = field(default_factory=WorkerConfig)
