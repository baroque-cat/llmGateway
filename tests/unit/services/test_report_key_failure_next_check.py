#!/usr/bin/env python3

"""
Unit tests for compute_next_check_time and _report_key_failure next-check logic.

Tests SVC-1 through SVC-8:
- SVC-1..SVC-6: compute_next_check_time maps each ErrorReason to the correct
  HealthPolicyConfig interval (hours, days, minutes).
- SVC-7: _report_key_failure uses compute_next_check_time instead of a
  hardcoded +1 minute.
- SVC-8: NO_QUOTA produces a next_check_time significantly longer than 1 minute.
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.config.schemas import HealthPolicyConfig, ProviderConfig
from src.core.constants import ErrorReason
from src.core.models import CheckResult
from src.core.policy_utils import compute_next_check_time

# ---------------------------------------------------------------------------
# SVC-1 through SVC-6: compute_next_check_time per ErrorReason
# ---------------------------------------------------------------------------


class TestComputeNextCheckTime:
    """Verify that compute_next_check_time returns the correct timedelta for each ErrorReason."""

    def _make_policy(self, **overrides: int) -> HealthPolicyConfig:
        """Create a HealthPolicyConfig with optional field overrides."""
        defaults = {
            "on_server_error_min": 30,
            "on_overload_min": 30,
            "on_other_error_hr": 1,
            "on_success_hr": 24,
            "on_rate_limit_hr": 1,
            "on_no_quota_hr": 6,
            "on_invalid_key_days": 10,
            "on_no_access_days": 10,
        }
        defaults.update(overrides)
        return HealthPolicyConfig(**defaults)

    # SVC-1: NO_QUOTA → now + on_no_quota_hr hours
    def test_compute_next_check_time_no_quota(self) -> None:
        policy = self._make_policy(on_no_quota_hr=6)
        before = datetime.now(UTC)
        result = compute_next_check_time(policy, ErrorReason.NO_QUOTA)
        after = datetime.now(UTC)
        expected_min = before + timedelta(hours=6)
        expected_max = after + timedelta(hours=6)
        assert expected_min <= result <= expected_max

    # SVC-2: RATE_LIMITED → now + on_rate_limit_hr hours
    def test_compute_next_check_time_rate_limited(self) -> None:
        policy = self._make_policy(on_rate_limit_hr=1)
        before = datetime.now(UTC)
        result = compute_next_check_time(policy, ErrorReason.RATE_LIMITED)
        after = datetime.now(UTC)
        expected_min = before + timedelta(hours=1)
        expected_max = after + timedelta(hours=1)
        assert expected_min <= result <= expected_max

    # SVC-3: INVALID_KEY → now + on_invalid_key_days days
    def test_compute_next_check_time_invalid_key(self) -> None:
        policy = self._make_policy(on_invalid_key_days=10)
        before = datetime.now(UTC)
        result = compute_next_check_time(policy, ErrorReason.INVALID_KEY)
        after = datetime.now(UTC)
        expected_min = before + timedelta(days=10)
        expected_max = after + timedelta(days=10)
        assert expected_min <= result <= expected_max

    # SVC-4: SERVER_ERROR → now + on_server_error_min minutes
    def test_compute_next_check_time_server_error(self) -> None:
        policy = self._make_policy(on_server_error_min=30)
        before = datetime.now(UTC)
        result = compute_next_check_time(policy, ErrorReason.SERVER_ERROR)
        after = datetime.now(UTC)
        expected_min = before + timedelta(minutes=30)
        expected_max = after + timedelta(minutes=30)
        assert expected_min <= result <= expected_max

    # SVC-5: OVERLOADED → now + on_overload_min minutes
    def test_compute_next_check_time_overloaded(self) -> None:
        policy = self._make_policy(on_overload_min=30)
        before = datetime.now(UTC)
        result = compute_next_check_time(policy, ErrorReason.OVERLOADED)
        after = datetime.now(UTC)
        expected_min = before + timedelta(minutes=30)
        expected_max = after + timedelta(minutes=30)
        assert expected_min <= result <= expected_max

    # SVC-6: UNKNOWN → now + on_other_error_hr hours
    def test_compute_next_check_time_unknown(self) -> None:
        policy = self._make_policy(on_other_error_hr=1)
        before = datetime.now(UTC)
        result = compute_next_check_time(policy, ErrorReason.UNKNOWN)
        after = datetime.now(UTC)
        expected_min = before + timedelta(hours=1)
        expected_max = after + timedelta(hours=1)
        assert expected_min <= result <= expected_max


# ---------------------------------------------------------------------------
# SVC-7 & SVC-8: _report_key_failure uses compute_next_check_time
# ---------------------------------------------------------------------------


class TestReportKeyFailureNextCheck:
    """Verify that _report_key_failure computes next_check_time from HealthPolicyConfig."""

    @pytest.mark.asyncio
    async def test_report_key_failure_uses_compute_next_check_time(self) -> None:
        """
        SVC-7: _report_key_failure() calls compute_next_check_time() instead of
        hardcoding +1 minute.  We patch compute_next_check_time and verify it is
        called with the provider's HealthPolicyConfig and the result's ErrorReason.
        """
        from src.services.gateway_service import _report_key_failure

        # --- Setup mocks ---
        db_manager = MagicMock()
        db_manager.keys.update_status = AsyncMock()

        accessor = MagicMock()
        provider_config = ProviderConfig(
            provider_type="openai_like", keys_path="keys/test/"
        )
        # Use non-default values so we can distinguish from +1 min
        provider_config.worker_health_policy = HealthPolicyConfig(
            on_no_quota_hr=6,
            on_rate_limit_hr=2,
            on_server_error_min=15,
            on_overload_min=10,
            on_other_error_hr=3,
            on_invalid_key_days=7,
            on_no_access_days=7,
        )
        accessor.get_provider_or_raise.return_value = provider_config

        result = CheckResult.fail(ErrorReason.NO_QUOTA, "No quota", 0.5, 429)

        # Patch compute_next_check_time to track the call
        with patch(
            "src.services.gateway_service.compute_next_check_time",
            side_effect=compute_next_check_time,
        ) as mock_compute:
            await _report_key_failure(
                db_manager=db_manager,
                key_id=1,
                provider_name="test-provider",
                model_name="gpt-4",
                result=result,
                accessor=accessor,
            )

            # Verify compute_next_check_time was called with the correct args
            mock_compute.assert_called_once_with(
                provider_config.worker_health_policy,
                ErrorReason.NO_QUOTA,
            )

        # Verify update_status was called with a computed next_check_time
        call_args = db_manager.keys.update_status.call_args
        next_check_time = call_args.kwargs.get("next_check_time")
        assert next_check_time is not None
        # The next_check_time must NOT be now + timedelta(minutes=1)
        # (the old hardcoded behaviour).  It should be now + hours.
        now = datetime.now(UTC)
        one_minute_later = now + timedelta(minutes=1)
        # With on_no_quota_hr=6, the next check should be ~6 hours away,
        # definitely more than 1 minute.
        assert next_check_time > one_minute_later

    @pytest.mark.asyncio
    async def test_report_key_failure_no_quota_longer_than_1min(self) -> None:
        """
        SVC-8: _report_key_failure with NO_QUOTA produces a next_check_time
        significantly longer than 1 minute (default on_no_quota_hr=6 >> 1 min).
        """
        from src.services.gateway_service import _report_key_failure

        db_manager = MagicMock()
        db_manager.keys.update_status = AsyncMock()

        accessor = MagicMock()
        provider_config = ProviderConfig(
            provider_type="openai_like", keys_path="keys/test/"
        )
        # Use default HealthPolicyConfig (on_no_quota_hr=6)
        accessor.get_provider_or_raise.return_value = provider_config

        result = CheckResult.fail(ErrorReason.NO_QUOTA, "No quota", 0.5, 429)

        await _report_key_failure(
            db_manager=db_manager,
            key_id=1,
            provider_name="test-provider",
            model_name="gpt-4",
            result=result,
            accessor=accessor,
        )

        call_args = db_manager.keys.update_status.call_args
        next_check_time = call_args.kwargs.get("next_check_time")
        assert next_check_time is not None

        now = datetime.now(UTC)
        one_minute_later = now + timedelta(minutes=1)
        # Default on_no_quota_hr=6 → next_check ≈ now + 6 hours, much > 1 min
        assert next_check_time > one_minute_later + timedelta(hours=1)
