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
    CircuitBreakerConfig, BackoffConfig
)

logger = logging.getLogger(__name__)

# Regex to find environment variable placeholders like ${VAR_NAME}
ENV_VAR_PATTERN = re.compile(r"^\$\{(?P<name>[A-Z0-9_]+)\}$")

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
                    "in the config but is not set. Please define it in your .env file or system environment."
                )
            return var_value
    
    return config_value


def _validate_config(config: Config):
    """
    Performs comprehensive validation on the fully loaded configuration object.
    """
    used_tokens: Set[str] = set()

    # --- Global Worker Config Validation ---
    if config.worker.max_concurrent_providers <= 0:
        raise ValueError("'worker.max_concurrent_providers' must be a positive integer.")

    if not config.providers:
        logger.warning("No providers are defined in the configuration file.")
        return

    for name, conf in config.providers.items():
        if not conf.enabled:
            continue

        # --- Core Provider Validations ---
        if not conf.provider_type:
            raise ValueError(f"Provider '{name}' is enabled but 'provider_type' is not set.")
        if not conf.keys_path:
            raise ValueError(f"Provider '{name}' is enabled but 'keys_path' is not set.")
        
        token = conf.access_control.gateway_access_token
        if not token:
            raise ValueError(f"Provider '{name}' is enabled but 'gateway_access_token' is not set.")
        if token in used_tokens:
            raise ValueError(
                f"Duplicate gateway_access_token '{token}' found for provider '{name}'. "
                "All gateway access tokens must be unique."
            )
        used_tokens.add(token)

        # --- Proxy Config Validation ---
        proxy_conf = conf.proxy_config
        valid_proxy_modes = {'none', 'static', 'stealth'}
        if proxy_conf.mode not in valid_proxy_modes:
            raise ValueError(
                f"Provider '{name}' has an invalid proxy mode '{proxy_conf.mode}'. Valid modes are: {valid_proxy_modes}"
            )

        # --- Gateway Policy Validations ---
        gateway_policy = conf.gateway_policy
        
        # Circuit Breaker validation
        cb_conf = gateway_policy.circuit_breaker
        if cb_conf.enabled:
            valid_cb_modes = {'auto_recovery', 'manual_reset'}
            if cb_conf.mode not in valid_cb_modes:
                raise ValueError(
                    f"Provider '{name}' has an invalid circuit breaker mode '{cb_conf.mode}'. "
                    f"Valid modes are: {valid_cb_modes}"
                )
            if cb_conf.failure_threshold <= 0:
                 raise ValueError(f"Provider '{name}': circuit_breaker 'failure_threshold' must be positive.")
            if cb_conf.jitter_sec < 0:
                 raise ValueError(f"Provider '{name}': circuit_breaker 'jitter_sec' must be non-negative.")
            if cb_conf.backoff.base_duration_sec <= 0:
                 raise ValueError(f"Provider '{name}': circuit_breaker 'base_duration_sec' must be positive.")
            if cb_conf.backoff.max_duration_sec <= cb_conf.backoff.base_duration_sec:
                 raise ValueError(f"Provider '{name}': circuit_breaker 'max_duration_sec' must be greater than 'base_duration_sec'.")

        # Retry Policy validation
        retry_conf = gateway_policy.retry
        if retry_conf.enabled:
            if retry_conf.on_key_error.attempts < 0 or retry_conf.on_server_error.attempts < 0:
                raise ValueError(f"Provider '{name}': Retry 'attempts' must be non-negative.")
            if retry_conf.on_server_error.backoff_sec < 0:
                 raise ValueError(f"Provider '{name}': Retry 'backoff_sec' must be non-negative.")


def load_config(path: str = "config/providers.yaml") -> Config:
    """
    Loads, resolves env variables, parses, and validates the configuration from a given path.

    This function is now responsible ONLY for loading and validation.
    It no longer creates a default file. If the file is not found, it raises
    a FileNotFoundError, guiding the user to use the config manager CLI.

    Args:
        path: The path to the YAML configuration file.

    Returns:
        A fully populated and validated Config object.

    Raises:
        FileNotFoundError: If the configuration file does not exist.
        ValueError: If the configuration is invalid.
    """
    if load_dotenv():
        logger.info("Loaded environment variables from .env file.")

    if not os.path.exists(path):
        raise FileNotFoundError(
            f"Configuration file not found at '{path}'.\n"
            f"Please create it first using the command: 'python main.py config --create type:name'"
        )

    with open(path, 'r', encoding='utf-8') as f:
        raw_config = yaml.safe_load(f) or {}

    resolved_config = _resolve_env_vars(raw_config)

    # --- Parse all configuration sections into dataclasses ---
    logging_data = resolved_config.get('logging', {})
    database_data = resolved_config.get('database', {})
    worker_data = resolved_config.get('worker', {})
    
    app_config = Config(
        debug=resolved_config.get('debug', False),
        database=DatabaseConfig(**database_data),
        logging=LoggingConfig(**logging_data),
        worker=WorkerConfig(**worker_data),
    )

    for name, provider_data in resolved_config.get('providers', {}).items():
        access_data = provider_data.get('access_control', {})
        health_data = provider_data.get('health_policy', {})
        proxy_data = provider_data.get('proxy_config', {})
        timeout_data = provider_data.get('timeouts', {})
        
        # Safely parse nested gateway policy sections
        gateway_policy_data = provider_data.get('gateway_policy', {})
        retry_data = gateway_policy_data.get('retry', {})
        retry_key_error_data = retry_data.get('on_key_error', {})
        retry_server_error_data = retry_data.get('on_server_error', {})
        cb_data = gateway_policy_data.get('circuit_breaker', {})
        cb_backoff_data = cb_data.get('backoff', {})
        
        # Instantiate all config objects
        gateway_policy = GatewayPolicyConfig(
            retry=RetryPolicyConfig(
                enabled=retry_data.get('enabled', False),
                on_key_error=RetryOnErrorConfig(**retry_key_error_data),
                on_server_error=RetryOnErrorConfig(**retry_server_error_data)
            ),
            circuit_breaker=CircuitBreakerConfig(
                enabled=cb_data.get('enabled', False),
                mode=cb_data.get('mode', 'auto_recovery'),
                failure_threshold=cb_data.get('failure_threshold', 10),
                jitter_sec=cb_data.get('jitter_sec', 5),
                backoff=BackoffConfig(**cb_backoff_data)
            )
        )

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
            timeouts=TimeoutConfig(**timeout_data),
            gateway_policy=gateway_policy,
        )
        app_config.providers[name] = provider_conf

    _validate_config(app_config)
    logger.info("Configuration loaded and validated successfully.")
    return app_config

