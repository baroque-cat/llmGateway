#!/usr/bin/env python3

import logging

# Import the full dataclass definitions for type checking.
from src.config.schemas import (
    Config,
    ErrorParsingConfig,
    GatewayPolicyConfig,
    HealthPolicyConfig,
    ProviderConfig,
)

# Import core enums for validation against a single source of truth.
from src.core.constants import (
    CircuitBreakerMode,
    DebugMode,
    ErrorReason,
    ProxyMode,
    StreamingMode,
)

logger = logging.getLogger(__name__)


class ConfigValidator:
    """
    Validates the fully loaded and merged Config object for business logic
    and consistency errors. This aligns with the plan to separate validation
    from loading.
    """

    def __init__(self) -> None:
        """
        Initializes the validator. It maintains a list of errors found during
        the validation process. This implements the "Error Accumulation" improvement.
        """
        self.errors: list[str] = []

    def validate(self, config: Config) -> None:
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
            raise ValueError(
                f"Configuration validation failed with {len(self.errors)} error(s):\n- {error_summary}"
            )

        logger.info("Configuration passed all validation checks.")

    def _add_error(self, message: str) -> None:
        """A helper to add an error message to the internal list."""
        self.errors.append(message)

    def _validate_global_config(self, config: Config) -> None:
        """
        Validates global configuration sections like 'worker' and 'database'.
        This corresponds to Step 2 of the plan.
        """
        if config.worker.max_concurrent_providers <= 0:
            self._add_error(
                "'worker.max_concurrent_providers' must be a positive integer."
            )

        if not config.database.password:
            self._add_error(
                "'database.password' is not set. It should be loaded from an environment variable."
            )

    def _validate_providers_config(self, config: Config) -> None:
        """
        Validates the 'providers' section, iterating through each instance.
        This is the most complex validation part, as planned in Step 2.
        """
        if not config.providers:
            logger.warning("Configuration validation: No providers are defined.")
            return

        used_tokens: set[str] = set()

        for name, provider_conf in config.providers.items():
            if not provider_conf.enabled:
                continue

            self._validate_single_provider(name, provider_conf, used_tokens)

    def _validate_single_provider(
        self, name: str, conf: ProviderConfig, used_tokens: set[str]
    ) -> None:
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
            self._add_error(
                f"Provider '{name}': 'access_control.gateway_access_token' must be set."
            )
        elif token in used_tokens:
            self._add_error(
                f"Provider '{name}': Duplicate 'gateway_access_token' found. Each enabled provider must have a unique token."
            )
        else:
            used_tokens.add(token)

        # --- Model Configuration Integrity ---
        if conf.default_model and conf.default_model not in conf.models:
            available_models = list(conf.models.keys())
            self._add_error(
                f"Provider '{name}': The 'default_model' ('{conf.default_model}') "
                f"is not defined in the 'models' section. Available models are: {available_models}"
            )

        # --- Mode Validation (Proxy, Circuit Breaker) ---
        proxy_mode = conf.proxy_config.mode
        if proxy_mode not in ProxyMode._value2member_map_:
            valid_proxy_modes = list(ProxyMode._value2member_map_.keys())
            self._add_error(
                f"Provider '{name}': Invalid proxy mode '{proxy_mode}'. Must be one of {valid_proxy_modes}."
            )

        if proxy_mode == "static" and not conf.proxy_config.static_url:
            self._add_error(
                f"Provider '{name}': Proxy mode is 'static' but 'static_url' is not set."
            )

        if proxy_mode == "stealth" and not conf.proxy_config.pool_list_path:
            self._add_error(
                f"Provider '{name}': Proxy mode is 'stealth' but 'pool_list_path' is not set."
            )

        cb_conf = conf.gateway_policy.circuit_breaker
        if (
            cb_conf.enabled
            and cb_conf.mode not in CircuitBreakerMode._value2member_map_
        ):
            valid_cb_modes = list(CircuitBreakerMode._value2member_map_.keys())
            self._add_error(
                f"Provider '{name}': Invalid circuit breaker mode '{cb_conf.mode}'. Must be one of {valid_cb_modes}."
            )

        # --- NEW: Gateway Policy Validation ---
        # This call validates all strict-mode settings in the gateway policy.
        self._validate_gateway_policy(name, conf.gateway_policy)

        # --- NEW: Health Policy Validation ---
        # This call integrates the new validation logic as planned.
        self._validate_health_policy(name, conf.worker_health_policy)

        # --- NEW: Error Parsing Validation ---
        # Validate error parsing configuration if enabled
        self._validate_error_parsing(name, conf.gateway_policy.error_parsing)

    def _validate_gateway_policy(self, name: str, policy: GatewayPolicyConfig) -> None:
        """
        Validates the strict-mode settings within the GatewayPolicyConfig.
        Ensures that all mode fields use only allowed enum values and that
        unsafe_status_mapping values are valid ErrorReasons.
        """
        # Validate debug_mode against DebugMode enum
        debug_mode_value = policy.debug_mode
        if debug_mode_value not in DebugMode._value2member_map_:
            valid_modes = list(DebugMode._value2member_map_.keys())
            self._add_error(
                f"Provider '{name}': Invalid debug mode '{debug_mode_value}'. "
                f"Must be one of {valid_modes}."
            )

        # Validate streaming_mode against StreamingMode enum
        streaming_mode_value = policy.streaming_mode
        if streaming_mode_value not in StreamingMode._value2member_map_:
            valid_modes = list(StreamingMode._value2member_map_.keys())
            self._add_error(
                f"Provider '{name}': Invalid streaming mode '{streaming_mode_value}'. "
                f"Must be one of {valid_modes}."
            )

        # Validate fast_status_mapping values against ErrorReason enum
        fast_mapping = policy.fast_status_mapping
        valid_error_reasons = set(ErrorReason._value2member_map_.keys())
        for status_code, error_reason_str in fast_mapping.items():
            # Validate status code is in the HTTP range (already guaranteed to be int by type system)
            if status_code < 100 or status_code >= 600:
                self._add_error(
                    f"Provider '{name}': In 'fast_status_mapping', key '{status_code}' "
                    f"is not a valid HTTP status code (100-599)."
                )

            # Validate the error reason string
            if error_reason_str not in valid_error_reasons:
                self._add_error(
                    f"Provider '{name}': In 'fast_status_mapping', value '{error_reason_str}' "
                    f"for status code {status_code} is not a valid ErrorReason. "
                    f"Valid options are: {sorted(valid_error_reasons)}."
                )

    def _validate_health_policy(self, name: str, policy: HealthPolicyConfig) -> None:
        """
        Validates the business logic and consistency of the HealthPolicyConfig.
        This new method modularizes the validation logic as planned.
        """
        # --- Logical Consistency Checks for Quarantine ---
        # This implements the core requirement of the refactoring.
        if policy.quarantine_after_days > policy.stop_checking_after_days:
            self._add_error(
                f"Provider '{name}': Health policy error. 'quarantine_after_days' ({policy.quarantine_after_days}) "
                f"cannot be greater than 'stop_checking_after_days' ({policy.stop_checking_after_days})."
            )

        # --- Positive Value Checks for Time Intervals ---
        # This ensures that all time-based settings are sensible.
        time_fields_to_check = {
            "on_server_error_min": policy.on_server_error_min,
            "on_overload_min": policy.on_overload_min,
            "on_other_error_hr": policy.on_other_error_hr,
            "on_success_hr": policy.on_success_hr,
            "on_rate_limit_hr": policy.on_rate_limit_hr,
            "on_no_quota_hr": policy.on_no_quota_hr,
            "on_invalid_key_days": policy.on_invalid_key_days,
            "on_no_access_days": policy.on_no_access_days,
            "quarantine_after_days": policy.quarantine_after_days,
            "quarantine_recheck_interval_days": policy.quarantine_recheck_interval_days,
            "stop_checking_after_days": policy.stop_checking_after_days,
            "verification_delay_sec": policy.verification_delay_sec,
        }

        for field_name, value in time_fields_to_check.items():
            if value <= 0:
                self._add_error(
                    f"Provider '{name}': Health policy field '{field_name}' must be a positive integer, but got {value}."
                )

        # --- Positive Value Checks for Batching ---
        if policy.batch_size <= 0:
            self._add_error(
                f"Provider '{name}': Health policy field 'batch_size' must be a positive integer, but got {policy.batch_size}."
            )

        # Batch delay can be zero, so we check for negative values.
        if policy.batch_delay_sec < 0:
            self._add_error(
                f"Provider '{name}': Health policy field 'batch_delay_sec' cannot be negative, but got {policy.batch_delay_sec}."
            )

        # --- Verification Loop Configuration ---
        if policy.verification_attempts <= 0:
            self._add_error(
                f"Provider '{name}': Health policy field 'verification_attempts' must be a positive integer, but got {policy.verification_attempts}."
            )
        if policy.verification_delay_sec < 60:
            self._add_error(
                f"Provider '{name}': Health policy field 'verification_delay_sec' must be at least 60 seconds to survive minute-based rate limits, but got {policy.verification_delay_sec}."
            )

        # --- Fast Status Mapping Validation ---
        # Validate fast_status_mapping values against ErrorReason enum
        fast_mapping = policy.fast_status_mapping
        valid_error_reasons = set(ErrorReason._value2member_map_.keys())
        for status_code, error_reason_str in fast_mapping.items():
            # Validate status code is in the HTTP range (already guaranteed to be int by type system)
            if status_code < 100 or status_code >= 600:
                self._add_error(
                    f"Provider '{name}': In 'worker_health_policy.fast_status_mapping', key '{status_code}' "
                    f"is not a valid HTTP status code (100-599)."
                )

            # Validate the error reason string
            if error_reason_str not in valid_error_reasons:
                self._add_error(
                    f"Provider '{name}': In 'worker_health_policy.fast_status_mapping', value '{error_reason_str}' "
                    f"for status code {status_code} is not a valid ErrorReason. "
                    f"Valid options are: {sorted(valid_error_reasons)}."
                )

    def _validate_error_parsing(self, name: str, config: ErrorParsingConfig) -> None:
        """
        Validates the error parsing configuration for a provider.

        This ensures that error parsing rules are properly configured and
        map to valid ErrorReason values.
        """
        if not config.enabled:
            return

        # Import ErrorReason here to avoid circular imports
        from src.core.constants import ErrorReason

        # Validate each rule
        for i, rule in enumerate(config.rules):
            # Validate status code (should be 4xx or 5xx)
            if rule.status_code < 400 or rule.status_code >= 600:
                self._add_error(
                    f"Provider '{name}': error_parsing.rules[{i}].status_code "
                    f"must be a 4xx or 5xx HTTP status code, got {rule.status_code}."
                )

            # Validate error_path is not empty (already guaranteed to be str by type system)
            if not rule.error_path:
                self._add_error(
                    f"Provider '{name}': error_parsing.rules[{i}].error_path "
                    f"must be a non-empty string, got '{rule.error_path}'."
                )

            # Validate match_pattern is not empty (already guaranteed to be str by type system)
            if not rule.match_pattern:
                self._add_error(
                    f"Provider '{name}': error_parsing.rules[{i}].match_pattern "
                    f"must be a non-empty string, got '{rule.match_pattern}'."
                )

            # Validate map_to is a valid ErrorReason value
            try:
                ErrorReason(rule.map_to)
            except ValueError:
                valid_values = [e.value for e in ErrorReason]
                self._add_error(
                    f"Provider '{name}': error_parsing.rules[{i}].map_to "
                    f"must be a valid ErrorReason value, got '{rule.map_to}'. "
                    f"Valid values: {valid_values}"
                )

            # Validate priority is non-negative
            if rule.priority < 0:
                self._add_error(
                    f"Provider '{name}': error_parsing.rules[{i}].priority "
                    f"must be non-negative, got {rule.priority}."
                )
