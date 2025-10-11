# src/config/schemas.py

from dataclasses import dataclass, field
from typing import Dict, List, Optional

@dataclass
class ProviderConfig:
    """
    Configuration for a single LLM provider.
    This structure holds all settings specific to one provider,
    such as paths, URLs, and model lists.
    """
    provider_type: str = ""
    enabled: bool = False
    keys_path: str = ""
    api_base_url: str = ""
    default_model: str = ""  # The model to use for testing keys
    models: Dict[str, List[str]] = field(default_factory=dict)
    use_proxy_list: Optional[str] = None

@dataclass
class Config:
    """
    The main configuration object for the entire application.
    It aggregates configurations for all providers.
    """
    providers: Dict[str, ProviderConfig] = field(default_factory=dict)

