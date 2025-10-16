# src/config/loader.py

import os
import re
import yaml
import logging
from typing import Set, Any, Dict, List

from dotenv import load_dotenv

from src.config.schemas import (
    Config, ProviderConfig, AccessControlConfig, HealthPolicyConfig, 
    ProxyConfig, LoggingConfig, DatabaseConfig
)
from src.config.defaults import get_default_config

logger = logging.getLogger(__name__)

# Regex to find environment variable placeholders like ${VAR_NAME}
ENV_VAR_PATTERN = re.compile(r"\$\{(?P<name>[A-Z0-9_]+)\}")

def _resolve_env_vars(config_value: Any) -> Any:
    """
    Recursively traverses a config structure (dicts, lists) and replaces
    placeholders like ${VAR_NAME} with their corresponding environment variable values.
    """
    if isinstance(config_value, dict):
        return {k: _resolve_env_vars(v) for k, v in config_value.items()}
    
    if isinstance(config_value, list):
        return [_resolve_env_vars(item) for item in config_value]

    if isinstance(config_value, str):
        match = ENV_VAR_PATTERN.match(config_value)
        if match:
            var_name = match.group("name")
            var_value = os.environ.get(var_name)
            if var_value is None:
                raise ValueError(
                    f"Configuration error: Environment variable '{var_name}' is referenced "
                    "in the config but is not set."
                )
            return var_value
    
    return config_value


def _validate_config(config: Config):
    """
    Performs validation on the loaded configuration.
    """
    used_tokens: Set[str] = set()

    for name, conf in config.providers.items():
        if conf.enabled:
            if not conf.provider_type:
                raise ValueError(f"Provider '{name}' is enabled but 'provider_type' is not set.")
            if not conf.keys_path:
                raise ValueError(f"Provider '{name}' is enabled but 'keys_path' is not set.")
            
            if conf.shared_key_status and not conf.default_model:
                raise ValueError(
                    f"Provider '{name}' has 'shared_key_status' enabled but "
                    "'default_model' is not set. A default model is required for this mode."
                )

            token = conf.access_control.gateway_access_token
            if not token:
                raise ValueError(f"Provider '{name}' is enabled but 'gateway_access_token' is not set.")
            
            if token in used_tokens:
                raise ValueError(
                    f"Duplicate gateway_access_token '{token}' found for provider '{name}'. "
                    "All gateway access tokens must be unique."
                )
            used_tokens.add(token)

            proxy_conf = conf.proxy_config
            valid_modes = {'none', 'static', 'stealth'}
            if proxy_conf.mode not in valid_modes:
                raise ValueError(
                    f"Provider '{name}' has an invalid proxy mode '{proxy_conf.mode}'. Valid modes are: {valid_modes}"
                )
            if proxy_conf.mode == 'static' and not proxy_conf.static_url:
                raise ValueError(
                    f"Provider '{name}' is in 'static' proxy mode but 'static_url' is not set."
                )
            if proxy_conf.mode == 'stealth' and not proxy_conf.pool_list_path:
                raise ValueError(
                    f"Provider '{name}' is in 'stealth' proxy mode but 'pool_list_path' is not set."
                )


def load_config(path: str = "config/providers.yaml") -> Config:
    """
    Loads, resolves env variables, parses, and validates the configuration.
    If the file doesn't exist, it creates a default one.
    """
    # This populates os.environ with variables from a .env file if it exists.
    # It will not override existing system environment variables.
    if load_dotenv():
        logger.info("Loaded environment variables from .env file.")

    if not os.path.exists(path):
        logger.warning(f"Configuration file not found at '{path}'. Creating a default one.")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            yaml.dump(get_default_config(), f, default_flow_style=False, sort_keys=False)

    with open(path, 'r', encoding='utf-8') as f:
        raw_config = yaml.safe_load(f) or {}

    # --- NEW: Resolve environment variables before parsing ---
    resolved_config = _resolve_env_vars(raw_config)

    # Parse global settings
    logging_data = resolved_config.get('logging', {})
    database_data = resolved_config.get('database', {})
    
    app_config = Config(
        debug=resolved_config.get('debug', False),
        database=DatabaseConfig(**database_data),
        logging=LoggingConfig(**logging_data),
    )

    # Parse provider-specific settings
    for name, provider_data in resolved_config.get('providers', {}).items():
        access_data = provider_data.get('access_control', {})
        health_data = provider_data.get('health_policy', {})
        proxy_data = provider_data.get('proxy_config', {})

        provider_conf = ProviderConfig(
            provider_type=provider_data.get('provider_type', ''),
            enabled=provider_data.get('enabled', False),
            keys_path=provider_data.get('keys_path', ''),
            api_base_url=provider_data.get('api_base_url', ''),
            default_model=provider_data.get('default_model', ''),
            shared_key_status=provider_data.get('shared_key_status', False),
            models=provider_data.get('models', {}),
            
            access_control=AccessControlConfig(**access_data),
            health_policy=HealthPolicyConfig(**health_data),
            proxy_config=ProxyConfig(**proxy_data),
        )
        app_config.providers[name] = provider_conf

    _validate_config(app_config)

    return app_config
