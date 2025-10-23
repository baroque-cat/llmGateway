# src/config/validator.py

import logging
from typing import List, Set

from src.config.schemas import Config, ProviderConfig

logger = logging.getLogger(__name__)

class ConfigValidator:
    """
    Validates the fully loaded and merged Config object for business logic
    and consistency errors. This aligns with the plan to separate validation
    from loading.
    """

    def __init__(self):
        """
        Initializes the validator. It maintains a list of errors found during
        the validation process. This implements the "Error Accumulation" improvement.
        """
        self.errors: List[str] = []

    def validate(self, config: Config):
        """
        The main public method to orchestrate the validation of the entire config object.
        This follows Step 1 of the plan.

        Args:
            config: The fully loaded Config object from the ConfigLoader.

        Raises:
            ValueError: If any validation checks fail, containing all detected errors.
        """
        self.errors.clear()

        # Sequentially call private validation methods for each config section.
        # This modular approach is part of the plan for clean, maintainable code.
        self._validate_global_config(config)
        self._validate_providers_config(config)

        if self.errors:
            # Combine all found errors into a single, user-friendly message.
            error_summary = "\n- ".join(self.errors)
            raise ValueError(f"Configuration validation failed with {len(self.errors)} error(s):\n- {error_summary}")
        
        logger.info("Configuration passed all validation checks.")

    def _add_error(self, message: str):
        """A helper to add an error message to the internal list."""
        self.errors.append(message)

    def _validate_global_config(self, config: Config):
        """
        Validates global configuration sections like 'worker' and 'database'.
        This corresponds to Step 2 of the plan.
        """
        if config.worker.max_concurrent_providers <= 0:
            self._add_error("'worker.max_concurrent_providers' must be a positive integer.")
        
        # We can assume database config is mostly correct due to schemas,
        # but a check for the password placeholder is good practice.
        if not config.database.password:
            self._add_error("'database.password' is not set. It should be loaded from an environment variable.")

    def _validate_providers_config(self, config: Config):
        """
        Validates the 'providers' section, iterating through each instance.
        This is the most complex validation part, as planned in Step 2.
        """
        if not config.providers:
            logger.warning("Configuration validation: No providers are defined.")
            return

        used_tokens: Set[str] = set()

        for name, provider_conf in config.providers.items():
            # As identified in "Potential Errors", we should skip most checks for disabled providers.
            if not provider_conf.enabled:
                continue
            
            self._validate_single_provider(name, provider_conf, used_tokens)

    def _validate_single_provider(self, name: str, conf: ProviderConfig, used_tokens: Set[str]):
        """
        Performs detailed validation for a single, enabled provider instance.
        This provides context-aware error messages, an identified improvement.
        """
        # --- Essential Fields ---
        if not conf.provider_type:
            self._add_error(f"Provider '{name}': 'provider_type' must be set.")
        if not conf.keys_path:
            self._add_error(f"Provider '{name}': 'keys_path' must be set.")

        # --- Access Token Validation ---
        token = conf.access_control.gateway_access_token
        if not token:
            self._add_error(f"Provider '{name}': 'access_control.gateway_access_token' must be set.")
        elif token in used_tokens:
            self._add_error(f"Provider '{name}': Duplicate 'gateway_access_token' found. Each enabled provider must have a unique token.")
        else:
            used_tokens.add(token)

        # --- Model Configuration Integrity ---
        # This check was specifically planned to ensure config correctness.
        if conf.default_model and conf.default_model not in conf.models:
            available_models = list(conf.models.keys())
            self._add_error(
                f"Provider '{name}': The 'default_model' ('{conf.default_model}') "
                f"is not defined in the 'models' section. Available models are: {available_models}"
            )

        # --- Mode Validation (Proxy, Circuit Breaker) ---
        proxy_mode = conf.proxy_config.mode
        valid_proxy_modes = {'none', 'static', 'stealth'}
        if proxy_mode not in valid_proxy_modes:
            self._add_error(f"Provider '{name}': Invalid proxy mode '{proxy_mode}'. Must be one of {valid_proxy_modes}.")
        
        if proxy_mode == 'static' and not conf.proxy_config.static_url:
            self._add_error(f"Provider '{name}': Proxy mode is 'static' but 'static_url' is not set.")
        
        if proxy_mode == 'stealth' and not conf.proxy_config.pool_list_path:
             self._add_error(f"Provider '{name}': Proxy mode is 'stealth' but 'pool_list_path' is not set.")

        cb_conf = conf.gateway_policy.circuit_breaker
        if cb_conf.enabled:
            valid_cb_modes = {'auto_recovery', 'manual_reset'}
            if cb_conf.mode not in valid_cb_modes:
                self._add_error(f"Provider '{name}': Invalid circuit breaker mode '{cb_conf.mode}'. Must be one of {valid_cb_modes}.")

