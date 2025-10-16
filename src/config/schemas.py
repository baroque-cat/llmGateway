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
    batch_delay_sec: int = 30

@dataclass
class ProxyConfig:
    """
    Configuration for proxy usage, supporting multiple operational modes.
    """
    mode: str = "none"
    static_url: Optional[str] = None
    pool_list_path: Optional[str] = None

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
    
    # If true, the probe will only test the 'default_model'. The resulting status
    # will be propagated to all other models for that key.
    shared_key_status: bool = False
    
    models: Dict[str, List[str]] = field(default_factory=dict)
    
    access_control: AccessControlConfig = field(default_factory=AccessControlConfig)
    health_policy: HealthPolicyConfig = field(default_factory=HealthPolicyConfig)
    proxy_config: ProxyConfig = field(default_factory=ProxyConfig)


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
    port: int = 5432
    user: str = "llm_gateway"
    password: str = ""  # Should be loaded from .env
    dbname: str = "llmgateway"

    def to_dsn(self) -> str:
        """
        Constructs a PostgreSQL Data Source Name (DSN) string from the config.
        """
        return f"postgresql://{self.user}:{self.password}@{self.host}:{self.port}/{self.dbname}"

@dataclass
class Config:
    """
    The main configuration object for the entire application.
    """
    debug: bool = False
    
    database: DatabaseConfig = field(default_factory=DatabaseConfig)
    
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    providers: Dict[str, ProviderConfig] = field(default_factory=dict)
