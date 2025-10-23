# src/services/probes/key_probe.py

import logging
from typing import List, Dict, Any
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
    This class now uses ConfigAccessor for accessing configuration, inherited from IResourceProbe.
    """

    async def _get_resources_to_check(self) -> List[Dict[str, Any]]:
        """
        Fetches key-model pairs due for a health check from the database.
        """
        return await self.db_manager.keys.get_keys_to_check()

    async def _check_resource(self, resource: Dict[str, Any]) -> CheckResult:
        """
        Checks a single API key against a specific model by calling the provider.
        It now uses the accessor to get provider configuration safely.
        """
        provider_name = resource['provider_name']
        key_value = resource['key_value']
        model_name = resource['model_name']
        key_id = resource['key_id']

        logger.debug(f"Checking key (ID: {key_id}) for provider '{provider_name}', model '{model_name}'.")

        try:
            # REFACTORED: Use the accessor to get provider config.
            # get_provider_or_raise is used because a key from the DB must have a
            # corresponding config. Its absence indicates a critical state mismatch.
            provider_config = self.accessor.get_provider_or_raise(provider_name)

            # Get the appropriate pre-configured HTTP client from the factory.
            client = await self.client_factory.get_client_for_provider(provider_name)

            # Get the provider logic instance using the provider factory.
            provider_instance = get_provider(provider_name, provider_config)
            
            # The 'check' call is now clean, without any proxy-related logic.
            result = await provider_instance.check(
                client=client,
                token=key_value,
                model=model_name,
            )
            return result

        except KeyError as e:
            # This specifically catches the error from get_provider_or_raise.
            logger.error(f"Configuration mismatch: {e}. Cannot check key ID {key_id}.")
            return CheckResult.fail(ErrorReason.BAD_REQUEST, str(e))
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
        This now uses the accessor to retrieve health policies.
        """
        key_id = resource['key_id']
        model_name = resource['model_name']
        provider_name = resource['provider_name']

        try:
            # REFACTORED: Use accessor to get provider config. A missing config
            # here is a critical failure.
            provider_config = self.accessor.get_provider_or_raise(provider_name)
        except KeyError as e:
            logger.error(f"Cannot update key status. {e}.")
            return

        next_check_time = self._calculate_next_check_time(provider_config.health_policy, result)
        status_str = 'valid' if result.ok else result.error_reason.value
        
        logger.info(
            f"Updating status for key ID {key_id}, model '{model_name}': "
            f"Status -> [{status_str}], "
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
        (This method's internal logic is correct and does not need changes.)
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

