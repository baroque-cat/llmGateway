# src/services/probes/key_probe.py

import logging
from typing import List, Dict, Any
from datetime import datetime, timedelta

from src.core.probes import IResourceProbe
from src.core.models import CheckResult
from src.core.enums import ErrorReason
from src.config.schemas import HealthPolicyConfig
from src.db import database
from src.providers import get_provider

logger = logging.getLogger(__name__)

class KeyProbe(IResourceProbe):
    """
    A concrete implementation of IResourceProbe for checking the health of API keys.
    """

    def _get_resources_to_check(self) -> List[Dict[str, Any]]:
        """
        Fetches all key-model pairs that are due for a health check from the database.
        """
        return database.get_keys_to_check(self.db_path)

    def _check_resource(self, resource: Dict[str, Any]) -> CheckResult:
        """
        Checks a single API key against a specific model.
        """
        provider_name = resource['provider_name']
        key_value = resource['key_value']
        model_name = resource['model_name']

        logger.debug(f"Checking key (ID: {resource['key_id']}) for provider '{provider_name}', model '{model_name}'.")

        provider_config = self.config.providers.get(provider_name)
        if not provider_config:
            return CheckResult.fail(ErrorReason.BAD_REQUEST, f"Provider '{provider_name}' not configured.")

        # --- Foundation for Stealth Mode ---
        # This is where we would fetch a proxy if stealth mode is enabled for this provider.
        # For now, we prepare the interface by passing `proxy=None`.
        proxy_address = None
        if provider_config.proxy_config.enabled:
            # In the future, this will call the database to get a valid proxy.
            # proxy_address = database.get_available_proxy(self.db_path, provider_name)
            logger.warning(f"Stealth mode is enabled for '{provider_name}', but proxy selection is not yet implemented.")
        
        provider_instance = get_provider(provider_name, provider_config)
        
        # Pass the proxy address to the check method. The provider implementation
        # will be responsible for using it.
        return provider_instance.check(token=key_value, model=model_name, proxy=proxy_address)

    def _update_resource_status(self, resource: Dict[str, Any], result: CheckResult):
        """
        Updates the key's status in the database based on the check result.
        """
        key_id = resource['key_id']
        model_name = resource['model_name']
        provider_name = resource['provider_name']

        provider_config = self.config.providers.get(provider_name)
        if not provider_config:
            logger.error(f"Cannot update key status. Provider '{provider_name}' not found in config.")
            return

        next_check_time = self._calculate_next_check_time(provider_config.health_policy, result)
        
        status_str = 'VALID' if result.ok else result.error_reason.value
        
        logger.info(
            f"Updating status for key ID {key_id}, model '{model_name}': "
            f"Status -> {status_str}, "
            f"Next check -> {next_check_time.strftime('%Y-%m-%d %H:%M:%S')}"
        )

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
        """
        now = datetime.utcnow()
        if result.ok:
            return now + timedelta(hours=policy.on_success_hr)

        # Match error reason to the corresponding policy interval.
        reason = result.error_reason
        if reason == ErrorReason.INVALID_KEY or reason == ErrorReason.NO_ACCESS:
            return now + timedelta(days=policy.on_invalid_key_days)
        elif reason == ErrorReason.RATE_LIMITED:
            return now + timedelta(minutes=policy.on_rate_limit_min)
        elif reason == ErrorReason.OVERLOADED or reason == ErrorReason.NO_QUOTA:
             return now + timedelta(minutes=policy.on_overload_min)
        elif reason == ErrorReason.SERVER_ERROR or reason == ErrorReason.NETWORK_ERROR or reason == ErrorReason.TIMEOUT:
            return now + timedelta(minutes=policy.on_server_error_min)
        else: # Covers UNKNOWN, BAD_REQUEST, etc.
            return now + timedelta(hours=policy.on_other_error_hr)

