#!/usr/bin/env python3

import logging
from typing import List, Dict, Any, Optional
# --- STEP 1: ADD THE REQUIRED IMPORT AS PLANNED ---
# Added 'timezone' to create timezone-aware datetime objects.
from datetime import datetime, timedelta, timezone

from src.core.probes import IResourceProbe
from src.core.models import CheckResult
from src.core.enums import ErrorReason
from src.config.schemas import HealthPolicyConfig
from src.providers import get_provider

logger = logging.getLogger(__name__)

class KeyProbe(IResourceProbe):
    """
    A concrete implementation of IResourceProbe for checking API key health.
    This probe implements an advanced, state-aware logic for scheduling checks
    based on the key's failure history.
    """

    async def _get_resources_to_check(self) -> List[Dict[str, Any]]:
        """
        Fetches key-model pairs due for a health check from the database.
        This method relies on the repository to return the `failing_since` timestamp
        for each resource that has previously failed.
        """
        return await self.db_manager.keys.get_keys_to_check()

    async def _check_resource(self, resource: Dict[str, Any]) -> CheckResult:
        """
        Checks a single API key against a specific model by calling the provider.
        """
        provider_name = resource['provider_name']
        key_value = resource['key_value']
        model_name = resource['model_name']
        key_id = resource['key_id']

        logger.debug(f"Checking key (ID: {key_id}) for provider '{provider_name}', model '{model_name}'.")

        try:
            # Use the accessor to get provider config. A missing config is a critical error.
            provider_config = self.accessor.get_provider_or_raise(provider_name)

            # Get the appropriate pre-configured HTTP client from the factory.
            client = await self.client_factory.get_client_for_provider(provider_name)

            # Get the provider logic instance using the provider factory.
            provider_instance = get_provider(provider_name, provider_config)
            
            # The 'check' call is clean, without any proxy-related logic.
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
        Updates the key's status in the database, calculating the next check time
        using the new state-aware logic.
        """
        key_id = resource['key_id']
        model_name = resource['model_name']
        provider_name = resource['provider_name']
        failing_since = resource.get('failing_since') # This can be None

        try:
            provider_config = self.accessor.get_provider_or_raise(provider_name)
        except KeyError as e:
            logger.error(f"Cannot update key status due to config error. {e}.")
            return

        # The core logic is now encapsulated in this calculation.
        next_check_time = self._calculate_next_check_time(
            policy=provider_config.worker_health_policy,
            result=result,
            failing_since=failing_since
        )
        
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

    def _calculate_next_check_time(
        self,
        policy: HealthPolicyConfig,
        result: CheckResult,
        failing_since: Optional[datetime]
    ) -> datetime:
        """
        Calculates the next check time based on a hierarchical health policy.
        This method implements the new state-aware logic with quarantine and
        permanent failure states.
        """
        # --- STEP 2 & 3: REPLACE THE PROBLEMATIC LINE AS PLANNED ---
        # Get the current time in UTC as a timezone-aware object.
        # This is critical for performing correct arithmetic with the 'failing_since'
        # timestamp, which is also timezone-aware from the database.
        # Using the naive datetime.utcnow() would cause a TypeError.
        now = datetime.now(timezone.utc)

        # 1. Highest priority: a successful check resets everything.
        if result.ok:
            return now + timedelta(hours=policy.on_success_hr)

        # The key is failing. The 'failing_since' timestamp determines the strategy.
        # This timestamp is set by the database layer on the first failure in a series.
        if failing_since:
            # This calculation is now safe because both 'now' and 'failing_since' are timezone-aware.
            time_failing = now - failing_since

            # 2. Second priority: check if we should stop checking altogether.
            # The DB query should already filter these out, but this is a safeguard.
            if time_failing > timedelta(days=policy.stop_checking_after_days):
                logger.warning(
                    f"Key has been failing for {time_failing.days} days. Exceeds 'stop_checking_after_days' "
                    f"of {policy.stop_checking_after_days}. Setting check far in the future."
                )
                return now + timedelta(days=365) # Effectively stop checking

            # 3. Third priority: check if the key is in quarantine.
            if time_failing > timedelta(days=policy.quarantine_after_days):
                logger.info(
                    f"Key has been failing for {time_failing.days} days. It is now in quarantine. "
                    f"Re-checking in {policy.quarantine_recheck_interval_days} days."
                )
                return now + timedelta(days=policy.quarantine_recheck_interval_days)

        # 4. Default case: The key is failing, but not yet in quarantine.
        # Use the specific error reason to determine the backoff period.
        reason = result.error_reason
        if reason == ErrorReason.INVALID_KEY:
            return now + timedelta(days=policy.on_invalid_key_days)
        elif reason == ErrorReason.NO_ACCESS:
            return now + timedelta(days=policy.on_no_access_days)
        elif reason == ErrorReason.RATE_LIMITED:
            return now + timedelta(hours=policy.on_rate_limit_hr) # Using the new _hr field
        elif reason == ErrorReason.NO_QUOTA:
             return now + timedelta(hours=policy.on_no_quota_hr)
        elif reason == ErrorReason.OVERLOADED:
             return now + timedelta(minutes=policy.on_overload_min)
        elif reason in {ErrorReason.SERVER_ERROR, ErrorReason.NETWORK_ERROR, ErrorReason.TIMEOUT}:
            return now + timedelta(minutes=policy.on_server_error_min)
        else: # Covers UNKNOWN, BAD_REQUEST, etc.
            return now + timedelta(hours=policy.on_other_error_hr)

