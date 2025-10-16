# src/services/probes/key_probe.py

import asyncio
import logging
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta

from src.core.probes import IResourceProbe
from src.core.models import CheckResult
from src.core.enums import ErrorReason
from src.config.schemas import HealthPolicyConfig
from src.providers import get_provider

logger = logging.getLogger(__name__)

class KeyProbe(IResourceProbe):
    """
    A concrete implementation of IResourceProbe for checking API key health (Async Version).
    """

    async def _get_resources_to_check(self) -> List[Dict[str, Any]]:
        """
        Fetches key-model pairs due for a health check from the database.
        """
        return await self.db_manager.keys.get_keys_to_check()

    async def _check_resource(self, resource: Dict[str, Any]) -> CheckResult:
        """
        Checks a single API key against a specific model by calling the provider.
        This is now a fully async operation.
        """
        provider_name = resource['provider_name']
        key_value = resource['key_value']
        model_name = resource['model_name']
        key_id = resource['key_id']

        logger.debug(f"Checking key (ID: {key_id}) for provider '{provider_name}', model '{model_name}'.")

        provider_config = self.config.providers.get(provider_name)
        if not provider_config:
            msg = f"Provider '{provider_name}' not configured. Cannot check key ID {key_id}."
            logger.error(msg)
            return CheckResult.fail(ErrorReason.BAD_REQUEST, msg)

        proxy_address: Optional[str] = None
        proxy_config = provider_config.proxy_config

        if proxy_config.mode == 'static':
            proxy_address = proxy_config.static_url
        elif proxy_config.mode == 'stealth':
            logger.warning(f"Stealth mode for '{provider_name}' is not yet fully implemented. No proxy will be used for probe.")
            # In the future: proxy_address = await self.db_manager.proxies.get_available_proxy(...)

        try:
            provider_instance = get_provider(provider_name, provider_config)
            
            # --- CRITICAL CHANGE: Direct await call, no more run_in_executor ---
            # The provider's `check` method is now a coroutine and can be awaited directly.
            # We pass the long-lived http_client down to the provider.
            result = await provider_instance.check(
                client=self.http_client,
                token=key_value,
                model=model_name,
                proxy=proxy_address
            )
            return result

        except Exception as e:
            logger.error(
                f"An unexpected exception occurred during check for key ID {key_id} "
                f"for provider '{provider_name}': {e}",
                exc_info=True
            )
            return CheckResult.fail(ErrorReason.UNKNOWN, f"Probe-level exception: {e}")

    async def _update_resource_status(self, resource: Dict[str, Any], result: CheckResult):
        """
        Updates the key's status in the database using the DatabaseManager.
        """
        key_id = resource['key_id']
        model_name = resource['model_name']
        provider_name = resource['provider_name']

        provider_config = self.config.providers.get(provider_name)
        if not provider_config:
            logger.error(f"Cannot update key status. Provider '{provider_name}' not found in config.")
            return

        next_check_time = self._calculate_next_check_time(provider_config.health_policy, result)
        status_str = 'valid' if result.ok else result.error_reason.value
        
        logger.info(
            f"Updating status for key ID {key_id}, model '{model_name}': "
            f"Status -> {status_str}, "
            f"Next check -> {next_check_time.strftime('%Y-%m-%d %H:%M:%S')}"
        )

        await self.db_manager.keys.update_status(
            key_id=key_id,
            model_name=model_name,
            provider_name=provider_name,
            result=result,
            next_check_time=next_check_time
        )

    def _calculate_next_check_time(self, policy: HealthPolicyConfig, result: CheckResult) -> datetime:
        """
        Calculates the next check time based on the health policy.
        """
        now = datetime.utcnow()
        if result.ok:
            return now + timedelta(hours=policy.on_success_hr)

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
        else:
            return now + timedelta(hours=policy.on_other_error_hr)
