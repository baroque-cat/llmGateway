# src/services/probes/key_probe.py

import logging
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta

from src.core.probes import IResourceProbe
from src.core.models import CheckResult
from src.core.enums import ErrorReason
from src.config.schemas import HealthPolicyConfig
from src.db import database
from src.providers import get_provider

# Standard logger setup for the module.
logger = logging.getLogger(__name__)

class KeyProbe(IResourceProbe):
    """
    A concrete implementation of IResourceProbe for checking the health of API keys.
    This probe is responsible for testing key validity against provider APIs,
    respecting proxy configurations.
    """

    def _get_resources_to_check(self) -> List[Dict[str, Any]]:
        """
        Fetches all key-model pairs that are due for a health check from the database.
        This method queries the database for records whose 'next_check_time' is in the past.
        """
        return database.get_keys_to_check(self.db_path)

    def _check_resource(self, resource: Dict[str, Any]) -> CheckResult:
        """
        Checks a single API key against a specific model, applying proxy settings.

        This method now contains the core logic to select a proxy based on the
        provider's configuration ('none', 'static', or 'stealth' modes).
        """
        provider_name = resource['provider_name']
        key_value = resource['key_value']
        model_name = resource['model_name']
        key_id = resource['key_id']

        logger.debug(f"Checking key (ID: {key_id}) for provider '{provider_name}', model '{model_name}'.")

        provider_config = self.config.providers.get(provider_name)
        if not provider_config:
            # This is a critical configuration error. The key exists in the DB for a provider
            # that is no longer in the config file. Return a failure result.
            msg = f"Provider '{provider_name}' not configured. Cannot check key ID {key_id}."
            logger.error(msg)
            return CheckResult.fail(ErrorReason.BAD_REQUEST, msg)

        # --- Proxy Selection Logic ---
        # Determine the proxy address based on the provider's configuration.
        proxy_address: Optional[str] = None
        proxy_config = provider_config.proxy_config

        if proxy_config.mode == 'static':
            if proxy_config.static_url:
                proxy_address = proxy_config.static_url
                logger.debug(f"Using static proxy '{proxy_address}' for provider '{provider_name}'.")
            else:
                # This case should be caught by the config loader validation,
                # but we add a warning here as a safeguard.
                logger.warning(
                    f"Provider '{provider_name}' is in 'static' mode, but static_url is empty. "
                    "Proceeding without proxy."
                )
        elif proxy_config.mode == 'stealth':
            # This block is a placeholder for the future implementation of stealth mode.
            # When implemented, it will query the database for a healthy, rotated proxy.
            logger.warning(
                f"Stealth mode is enabled for '{provider_name}', but proxy selection is not yet implemented. "
                "Proceeding without proxy."
            )
            # In the future, this will be:
            # proxy_address = database.get_available_proxy(self.db_path, provider_name)
        
        # If mode is 'none' (or any other case), proxy_address remains None, and no proxy is used.

        try:
            # Get an instance of the provider class (e.g., GeminiProvider, OpenAILikeProvider).
            provider_instance = get_provider(provider_name, provider_config)
            
            # Perform the actual check by calling the provider's check method.
            # IMPORTANT: We pass the `proxy_address` as a keyword argument.
            # The concrete provider implementations (e.g., gemini.py) MUST be updated
            # to accept and use this 'proxy' argument in their `check` methods.
            return provider_instance.check(token=key_value, model=model_name, proxy=proxy_address)

        except Exception as e:
            # Catch any unexpected errors during provider instantiation or the check itself.
            logger.error(
                f"An unexpected exception occurred during check for key ID {key_id} "
                f"for provider '{provider_name}': {e}",
                exc_info=True # Include stack trace in the log for debugging.
            )
            return CheckResult.fail(ErrorReason.UNKNOWN, f"Probe-level exception: {e}")


    def _update_resource_status(self, resource: Dict[str, Any], result: CheckResult):
        """
        Updates the key's status in the database based on the check result.
        This method calculates the next check time according to the health policy
        and writes the new status to the database.
        """
        key_id = resource['key_id']
        model_name = resource['model_name']
        provider_name = resource['provider_name']

        provider_config = self.config.providers.get(provider_name)
        if not provider_config:
            logger.error(f"Cannot update key status. Provider '{provider_name}' not found in config.")
            return

        # Calculate when this key-model pair should be checked next.
        next_check_time = self._calculate_next_check_time(provider_config.health_policy, result)
        
        # Determine the status string: 'valid' on success, or the error reason on failure.
        status_str = 'valid' if result.ok else result.error_reason.value
        
        logger.info(
            f"Updating status for key ID {key_id}, model '{model_name}': "
            f"Status -> {status_str}, "
            f"Next check -> {next_check_time.strftime('%Y-%m-%d %H:%M:%S')}"
        )

        # Call the database function to persist the new status.
        database.update_key_model_status(
            db_path=self.db_path,
            key_id=key_id,
            model_name=model_name,
            status=status_str,
            next_check_time=next_check_time,
            status_code=result.status_code,
            response_time=result.response_time,
            error_message=result.message
        )

    def _calculate_next_check_time(self, policy: HealthPolicyConfig, result: CheckResult) -> datetime:
        """
        Calculates the next check time based on the health policy and check result.
        This encapsulates the business logic for scheduling re-checks.
        """
        now = datetime.utcnow()
        if result.ok:
            return now + timedelta(hours=policy.on_success_hr)

        # Match the specific error reason to the corresponding interval from the policy.
        reason = result.error_reason
        if reason in {ErrorReason.INVALID_KEY, ErrorReason.NO_ACCESS}:
            return now + timedelta(days=policy.on_invalid_key_days)
        elif reason == ErrorReason.RATE_LIMITED:
            return now + timedelta(minutes=policy.on_rate_limit_min)
        elif reason == ErrorReason.NO_QUOTA:
             return now + timedelta(hours=policy.on_no_quota_hr)
        elif reason == ErrorReason.OVERLOADED:
             return now + timedelta(minutes=policy.on_overload_min)
        elif reason in {ErrorReason.SERVER_ERROR, ErrorReason.NETWORK_ERROR, ErrorReason.TIMEOUT}:
            return now + timedelta(minutes=policy.on_server_error_min)
        else: # Covers UNKNOWN, BAD_REQUEST, etc., with a general-purpose interval.
            return now + timedelta(hours=policy.on_other_error_hr)

