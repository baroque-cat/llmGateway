# src/config/schemas.py

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any

# --- NEW: Dataclass to hold detailed information for each model ---
@dataclass
class ModelInfo:
    """
    Represents the specific configuration for a single model within a provider.
    This allows for a config-driven approach to handling multimodal APIs.
    """
    # The suffix appended to the provider's base URL to form the full endpoint.
    # e.g., ":generateContent" for Gemini text, "/chat/completions" for OpenAI.
    endpoint_suffix: str = ""
    # The minimal, valid JSON payload required to perform a health check on this model.
    test_payload: Dict[str, Any] = field(default_factory=dict)


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

@dataclass
class RetryOnErrorConfig:
    """Defines retry behavior for a specific error category."""
    attempts: int = 0
    backoff_sec: float = 1.0
    backoff_factor: float = 2.0

@dataclass
class RetryPolicyConfig:
    """Container for the gateway's retry policies."""
    enabled: bool = False
    on_key_error: RetryOnErrorConfig = field(default_factory=RetryOnErrorConfig)
    on_server_error: RetryOnErrorConfig = field(default_factory=RetryOnErrorConfig)

@dataclass
class BackoffConfig:
    """Configuration for the exponential backoff strategy of the circuit breaker."""
    base_duration_sec: int = 30
    max_duration_sec: int = 1800
    factor: float = 2.0

@dataclass
class CircuitBreakerConfig:
    """Configuration for the circuit breaker mechanism."""
    enabled: bool = False
    mode: str = 'auto_recovery'
    failure_threshold: int = 10
    backoff: BackoffConfig = field(default_factory=BackoffConfig)
    jitter_sec: int = 5

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
    
    # --- REFACTORED: The structure of 'models' has been changed. ---
    # It is no longer a dict with a list of strings, but a dictionary mapping
    # a model's name to its detailed configuration (ModelInfo).
    models: Dict[str, ModelInfo] = field(default_factory=dict)
    
    access_control: AccessControlConfig = field(default_factory=AccessControlConfig)
    health_policy: HealthPolicyConfig = field(default_factory=HealthPolicyConfig)
    proxy_config: ProxyConfig = field(default_factory=ProxyConfig)
    timeouts: TimeoutConfig = field(default_factory=TimeoutConfig)
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

@dataclass
class WorkerConfig:
    """Global settings specifically for the background worker service."""
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
    worker: WorkerConfig = field(default_factory=WorkerConfig)
