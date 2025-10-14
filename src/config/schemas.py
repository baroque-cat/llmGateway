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
    on_server_error_min: int = 10
    on_invalid_key_days: int = 10
    on_other_error_hr: int = 1
    batch_size: int = 30  # Number of keys to check in a single batch.
    batch_delay_sec: int = 15  # Delay in seconds between batches for the same provider.

@dataclass
class ProxyConfig:
    """
    Configuration for proxy usage, supporting multiple operational modes.
    """
    # Defines the proxy mode:
    # 'none': (Default) Direct connection, no proxy is used.
    # 'static': A single, fixed proxy is used for all requests for this provider.
    # 'stealth': A pool of proxies is used, with health checks and rotation (future implementation).
    mode: str = "none"

    # The URL for the proxy when mode is 'static'.
    # e.g., "http://user:pass@host:port" or "socks5://host:port"
    static_url: Optional[str] = None

    # The file path to the list of proxies when mode is 'stealth'.
    pool_list_path: Optional[str] = None

@dataclass
class ProviderConfig:
    """
    Configuration for a single LLM provider instance.
    This structure holds all settings specific to one named provider instance,
    such as paths, URLs, model lists, and behavioral policies.
    """
    provider_type: str = ""
    enabled: bool = False
    keys_path: str = ""
    api_base_url: str = ""
    default_model: str = ""
    models: Dict[str, List[str]] = field(default_factory=dict)
    
    # Nested configuration objects for better structure and clarity.
    # default_factory is used to ensure each ProviderConfig instance gets
    # a unique, mutable instance of these config objects.
    access_control: AccessControlConfig = field(default_factory=AccessControlConfig)
    health_policy: HealthPolicyConfig = field(default_factory=HealthPolicyConfig)
    proxy_config: ProxyConfig = field(default_factory=ProxyConfig)

@dataclass
class Config:
    """
    The main configuration object for the entire application.
    It aggregates configurations for all provider instances and holds global settings.
    """
    # --- NEW: Global application settings ---
    # Enables detailed operational logging to stdout.
    debug: bool = False
    
    # Path to the file where periodic summary reports will be written.
    summary_log_path: str = "data/summary.log"
    
    # Interval in minutes for writing the summary report.
    summary_interval_min: int = 60
    
    # --- Existing provider configurations ---
    providers: Dict[str, ProviderConfig] = field(default_factory=dict)
