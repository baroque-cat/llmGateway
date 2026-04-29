#!/usr/bin/env python3

"""
Integration test for _report_key_failure computing next_check_time from HealthPolicyConfig.

Test INT-5: _report_key_failure in a real gateway flow computes next_check_time
from HealthPolicyConfig (not a hardcoded +1 minute).
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.config.schemas import HealthPolicyConfig, ProviderConfig
from src.core.constants import ErrorReason
from src.core.models import CheckResult

# ---------------------------------------------------------------------------
# INT-5: _report_key_failure computes next_check_time from policy
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_report_key_failure_integration_next_check_from_policy() -> None:
    """
    INT-5: _report_key_failure in a real gateway flow computes next_check_time
    from HealthPolicyConfig, not from a hardcoded timedelta(minutes=1).

    This test verifies the full integration path:
    1. accessor.get_provider_or_raise() returns a ProviderConfig
    2. provider_config.worker_health_policy is the HealthPolicyConfig
    3. compute_next_check_time(policy, reason) is called
    4. db_manager.keys.update_status() receives the computed next_check_time
    """
    from src.services.gateway_service import _report_key_failure

    # --- Setup ---
    db_manager = MagicMock()
    db_manager.keys.update_status = AsyncMock()

    accessor = MagicMock()

    # Create a ProviderConfig with custom HealthPolicyConfig values
    # so we can distinguish the computed time from +1 minute
    provider_config = ProviderConfig(provider_type="openai_like")
    provider_config.worker_health_policy = HealthPolicyConfig(
        on_server_error_min=15,
        on_overload_min=20,
        on_other_error_hr=3,
        on_success_hr=24,
        on_rate_limit_hr=2,
        on_no_quota_hr=6,
        on_invalid_key_days=7,
        on_no_access_days=7,
    )
    accessor.get_provider_or_raise.return_value = provider_config

    # Create a CheckResult with RATE_LIMITED
    result = CheckResult.fail(ErrorReason.RATE_LIMITED, "Rate limited", 0.5, 429)

    # --- Execute ---
    await _report_key_failure(
        db_manager=db_manager,
        key_id=42,
        provider_name="test-provider",
        model_name="gpt-4",
        result=result,
        accessor=accessor,
    )

    # --- Verify ---
    # 1. accessor was called to get the provider config
    accessor.get_provider_or_raise.assert_called_once_with("test-provider")

    # 2. db_manager.keys.update_status was called
    db_manager.keys.update_status.assert_called_once()

    # 3. The next_check_time was computed from HealthPolicyConfig
    call_kwargs = db_manager.keys.update_status.call_args.kwargs
    next_check_time = call_kwargs.get("next_check_time")
    assert next_check_time is not None, "next_check_time must be provided"

    # 4. The next_check_time matches the policy: RATE_LIMITED → on_rate_limit_hr=2
    now = datetime.now(UTC)
    expected_min = now + timedelta(hours=2) - timedelta(seconds=2)
    expected_max = now + timedelta(hours=2) + timedelta(seconds=2)
    assert expected_min <= next_check_time <= expected_max, (
        f"next_check_time {next_check_time} should be approximately "
        f"now + 2 hours (on_rate_limit_hr=2), not now + 1 minute"
    )

    # 5. The next_check_time is NOT now + 1 minute (old hardcoded behavior)
    one_minute_later = now + timedelta(minutes=1)
    assert next_check_time > one_minute_later, (
        "next_check_time must be significantly > 1 minute — "
        "the old hardcoded +1 min behavior is removed"
    )

    # 6. Verify other kwargs are correct
    assert call_kwargs.get("key_id") == 42
    assert call_kwargs.get("model_name") == "gpt-4"
    assert call_kwargs.get("provider_name") == "test-provider"
    assert call_kwargs.get("result") == result


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
