# src/config/loader.py

import os
import re
import yaml
import logging
from typing import Set, Any, Dict, List

from dotenv import load_dotenv

from src.config.schemas import (
    Config, ProviderConfig, AccessControlConfig, HealthPolicyConfig,
    ProxyConfig, LoggingConfig, DatabaseConfig, TimeoutConfig, WorkerConfig,
    GatewayPolicyConfig, RetryPolicyConfig, RetryOnErrorConfig,
    CircuitBreakerConfig, BackoffConfig,
    # --- NEW: Import the new ModelInfo dataclass ---
    ModelInfo
)

logger = logging.getLogger(__name__)

ENV_VAR_PATTERN = re.compile(r"^\$\{(?P<name>[A-Z0-9_]+)\}$")

def _resolve_env_vars(config_value: Any) -> Any:
    """
    Recursively traverses a config structure and replaces ${VAR_NAME} placeholders.
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
                    f"Configuration error: Environment variable '{var_name}' is not set."
                )
            return var_value
    
    return config_value


def _validate_config(config: Config):
    """
    Performs comprehensive validation on the fully loaded configuration object.
    """
    used_tokens: Set[str] = set()

    if config.worker.max_concurrent_providers <= 0:
        raise ValueError("'worker.max_concurrent_providers' must be a positive integer.")

    if not config.providers:
        logger.warning("No providers are defined in the configuration file.")
        return

    for name, conf in config.providers.items():
        if not conf.enabled:
            continue

        if not conf.provider_type:
            raise ValueError(f"Provider '{name}': 'provider_type' is not set.")
        if not conf.keys_path:
            raise ValueError(f"Provider '{name}': 'keys_path' is not set.")
        
        token = conf.access_control.gateway_access_token
        if not token:
            raise ValueError(f"Provider '{name}': 'gateway_access_token' is not set.")
        if token in used_tokens:
            raise ValueError(f"Duplicate 'gateway_access_token' found for provider '{name}'.")
        used_tokens.add(token)

        # --- NEW: Validation for model configuration integrity ---
        # This ensures that if a default_model is specified, it actually exists
        # in the models dictionary, preventing runtime errors.
        if conf.default_model and conf.default_model not in conf.models:
            raise ValueError(
                f"Provider '{name}': The 'default_model' ('{conf.default_model}') "
                f"is not defined in the 'models' section. Available models are: {list(conf.models.keys())}"
            )
        
        proxy_conf = conf.proxy_config
        valid_proxy_modes = {'none', 'static', 'stealth'}
        if proxy_conf.mode not in valid_proxy_modes:
            raise ValueError(f"Provider '{name}': Invalid proxy mode '{proxy_conf.mode}'.")

        cb_conf = conf.gateway_policy.circuit_breaker
        if cb_conf.enabled:
            valid_cb_modes = {'auto_recovery', 'manual_reset'}
            if cb_conf.mode not in valid_cb_modes:
                raise ValueError(f"Provider '{name}': Invalid circuit breaker mode '{cb_conf.mode}'.")
        
        # Other validations remain the same...


def load_config(path: str = "config/providers.yaml") -> Config:
    """
    Loads, resolves env variables, parses, and validates the configuration.
    """
    if load_dotenv():
        logger.info("Loaded environment variables from .env file.")

    if not os.path.exists(path):
        raise FileNotFoundError(f"Configuration file not found at '{path}'.")

    with open(path, 'r', encoding='utf-8') as f:
        raw_config = yaml.safe_load(f) or {}

    resolved_config = _resolve_env_vars(raw_config)

    app_config = Config(
        debug=resolved_config.get('debug', False),
        database=DatabaseConfig(**resolved_config.get('database', {})),
        logging=LoggingConfig(**resolved_config.get('logging', {})),
        worker=WorkerConfig(**resolved_config.get('worker', {})),
    )

    for name, provider_data in resolved_config.get('providers', {}).items():
        # --- REFACTORED: Parse the new structured 'models' dictionary ---
        # Instead of passing the raw dictionary, we now iterate through it and
        # create ModelInfo objects, ensuring the data conforms to our new schema.
        models_from_yaml = provider_data.get('models', {})
        models_map = {
            model_name: ModelInfo(**model_data)
            for model_name, model_data in models_from_yaml.items()
        }

        gateway_policy_data = provider_data.get('gateway_policy', {})
        retry_data = gateway_policy_data.get('retry', {})
        cb_data = gateway_policy_data.get('circuit_breaker', {})
        
        gateway_policy = GatewayPolicyConfig(
            retry=RetryPolicyConfig(
                enabled=retry_data.get('enabled', False),
                on_key_error=RetryOnErrorConfig(**retry_data.get('on_key_error', {})),
                on_server_error=RetryOnErrorConfig(**retry_data.get('on_server_error', {}))
            ),
            circuit_breaker=CircuitBreakerConfig(
                enabled=cb_data.get('enabled', False),
                mode=cb_data.get('mode', 'auto_recovery'),
                failure_threshold=cb_data.get('failure_threshold', 10),
                jitter_sec=cb_data.get('jitter_sec', 5),
                backoff=BackoffConfig(**cb_data.get('backoff', {}))
            )
        )

        provider_conf = ProviderConfig(
            provider_type=provider_data.get('provider_type', ''),
            enabled=provider_data.get('enabled', True),
            keys_path=provider_data.get('keys_path', ''),
            api_base_url=provider_data.get('api_base_url', ''),
            default_model=provider_data.get('default_model', ''),
            shared_key_status=provider_data.get('shared_key_status', False),
            models=models_map,  # Pass the parsed map of ModelInfo objects
            access_control=AccessControlConfig(**provider_data.get('access_control', {})),
            health_policy=HealthPolicyConfig(**provider_data.get('health_policy', {})),
            proxy_config=ProxyConfig(**provider_data.get('proxy_config', {})),
            timeouts=TimeoutConfig(**provider_data.get('timeouts', {})),
            gateway_policy=gateway_policy,
        )
        app_config.providers[name] = provider_conf

    _validate_config(app_config)
    logger.info("Configuration loaded and validated successfully.")
    return app_config
