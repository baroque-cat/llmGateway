# src/config/loader.py

import os
import yaml
from typing import Set

from src.config.schemas import Config, ProviderConfig, AccessControlConfig, HealthPolicyConfig, ProxyConfig
from src.config.defaults import get_default_config


def _validate_config(config: Config):
    """
    Performs validation on the loaded configuration.

    Args:
        config: The fully loaded Config object.

    Raises:
        ValueError: If any validation rule is violated.
    """
    used_tokens: Set[str] = set()

    for name, conf in config.providers.items():
        if conf.enabled:
            # Basic field validation
            if not conf.provider_type:
                raise ValueError(f"Provider '{name}' is enabled but 'provider_type' is not set.")
            if not conf.keys_path:
                raise ValueError(f"Provider '{name}' is enabled but 'keys_path' is not set.")
            if not conf.default_model:
                raise ValueError(f"Provider '{name}' is enabled but 'default_model' is not set.")
            
            # Access token validation
            token = conf.access_control.gateway_access_token
            if not token:
                raise ValueError(f"Provider '{name}' is enabled but 'gateway_access_token' is not set.")
            
            if token in used_tokens:
                raise ValueError(
                    f"Duplicate gateway_access_token '{token}' found for provider '{name}'. "
                    "All gateway access tokens must be unique across all provider instances."
                )
            used_tokens.add(token)

            # --- NEW PROXY CONFIGURATION VALIDATION LOGIC ---
            proxy_conf = conf.proxy_config
            valid_modes = {'none', 'static', 'stealth'}

            # 1. Check if the specified mode is one of the allowed values.
            if proxy_conf.mode not in valid_modes:
                raise ValueError(
                    f"Provider '{name}' has an invalid proxy mode '{proxy_conf.mode}'. "
                    f"Valid modes are: {valid_modes}"
                )

            # 2. If mode is 'static', ensure the URL is provided.
            if proxy_conf.mode == 'static' and not proxy_conf.static_url:
                raise ValueError(
                    f"Provider '{name}' is in 'static' proxy mode but 'static_url' is not set."
                )
            
            # 3. If mode is 'stealth', ensure the path to the proxy list is provided.
            if proxy_conf.mode == 'stealth' and not proxy_conf.pool_list_path:
                raise ValueError(
                    f"Provider '{name}' is in 'stealth' proxy mode but 'pool_list_path' is not set."
                )


def load_config(path: str = "config/providers.yaml") -> Config:
    """
    Loads configuration from a YAML file.
    If the file does not exist, it creates a default one.
    It parses the raw data into structured Config objects and validates them.
    
    Args:
        path: The path to the YAML configuration file.

    Returns:
        A populated and validated Config object.
    """
    if not os.path.exists(path):
        print(f"Configuration file not found at '{path}'. Creating a default one.")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            yaml.dump(get_default_config(), f, default_flow_style=False, sort_keys=False)

    with open(path, 'r', encoding='utf-8') as f:
        raw_config = yaml.safe_load(f) or {}

    app_config = Config()

    for name, provider_data in raw_config.get('providers', {}).items():
        # Safely get nested dictionaries, defaulting to empty dicts if a section is missing.
        # This allows dataclasses to use their default values.
        access_data = provider_data.get('access_control', {})
        health_data = provider_data.get('health_policy', {})
        proxy_data = provider_data.get('proxy_config', {})

        provider_conf = ProviderConfig(
            provider_type=provider_data.get('provider_type', ''),
            enabled=provider_data.get('enabled', False),
            keys_path=provider_data.get('keys_path', ''),
            api_base_url=provider_data.get('api_base_url', ''),
            default_model=provider_data.get('default_model', ''),
            models=provider_data.get('models', {}),
            
            # Create nested dataclass objects from the parsed dictionaries.
            access_control=AccessControlConfig(**access_data),
            health_policy=HealthPolicyConfig(**health_data),
            proxy_config=ProxyConfig(**proxy_data)
        )
        app_config.providers[name] = provider_conf

    # Perform validation after loading all providers.
    _validate_config(app_config)

    return app_config
