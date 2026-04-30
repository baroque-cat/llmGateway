# tests/test_batching/test_callback.py
"""Callback pattern unit tests for IResourceProbe (scenarios UT-03..UT-11)."""

from collections.abc import Callable
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.config.schemas import AdaptiveBatchingConfig, HealthPolicyConfig
from src.core.constants import ErrorReason
from src.core.models import CheckResult
from src.core.probes import BatchCallback, IResourceProbe


class CallbackTestProbe(IResourceProbe):
    """Minimal concrete probe for callback testing — no side effects."""

    async def _get_resources_to_check(self) -> list:
        return []

    async def _check_resource(self, resource):
        return CheckResult.success()

    async def _update_resource_status(self, resource, result):
        pass


def _make_probe(on_batch_complete=None):
    """Helper to create a probe with mocked dependencies."""
    mock_accessor = MagicMock()
    mock_accessor.get_keeper_concurrency.return_value = 10
    mock_accessor.get_health_policy.return_value = HealthPolicyConfig(
        adaptive_batching=AdaptiveBatchingConfig(
            start_batch_size=10,
            start_batch_delay_sec=15.0,
        ),
    )
    mock_db = MagicMock()
    mock_client_factory = MagicMock()
    return CallbackTestProbe(
        mock_accessor,
        mock_db,
        mock_client_factory,
        on_batch_complete=on_batch_complete,
    )


# UT-03: BatchCallback is correct type alias
def test_ut03_batchcallback_is_correct_type_alias():
    """BatchCallback must be Callable[[str, int, float, int, int, int], None]."""
    expected = Callable[[str, int, float, int, int, int], None]
    assert BatchCallback == expected


# UT-04: __init__ with no on_batch_complete defaults to None
def test_ut04_default_on_batch_complete_is_none():
    """Creating a probe without on_batch_complete leaves _on_batch_complete as None."""
    probe = _make_probe(on_batch_complete=None)
    assert probe._on_batch_complete is None


# UT-05: __init__ stores passed callback
def test_ut05_stores_passed_callback():
    """Creating a probe with a callback stores it in _on_batch_complete."""
    callback_called = []

    def my_callback(
        provider_name,
        batch_size,
        batch_delay,
        rate_limit_events,
        backoff_events,
        recovery_events,
    ):
        callback_called.append((provider_name, batch_size))

    probe = _make_probe(on_batch_complete=my_callback)
    assert probe._on_batch_complete is my_callback


# UT-06: _process_provider_batch calls callback after each batch
@pytest.mark.asyncio
async def test_ut06_callback_called_after_batch():
    """Callback is invoked once per batch with updated controller state."""
    callback_args = []

    def my_callback(
        provider_name,
        batch_size,
        batch_delay,
        rate_limit_events,
        backoff_events,
        recovery_events,
    ):
        callback_args.append(
            {
                "provider_name": provider_name,
                "batch_size": batch_size,
                "batch_delay": batch_delay,
                "rate_limit_events": rate_limit_events,
                "backoff_events": backoff_events,
                "recovery_events": recovery_events,
            }
        )

    probe = _make_probe(on_batch_complete=my_callback)
    probe._check_resource = AsyncMock(return_value=CheckResult.success())
    probe._update_resource_status = AsyncMock()

    resources = [{"key_id": i, "provider_name": "test_provider"} for i in range(10)]
    await probe._process_provider_batch("test_provider", resources)

    assert len(callback_args) >= 1
    last = callback_args[-1]
    assert last["provider_name"] == "test_provider"
    # batch_size should be > initial (ramp-up after success)
    assert last["batch_size"] >= 10


# UT-07: no callback call when on_batch_complete is None
@pytest.mark.asyncio
async def test_ut07_no_callback_when_none():
    """When on_batch_complete is None, the method works without errors."""
    probe = _make_probe(on_batch_complete=None)
    probe._check_resource = AsyncMock(return_value=CheckResult.success())
    probe._update_resource_status = AsyncMock()

    resources = [{"key_id": i, "provider_name": "test_provider"} for i in range(10)]
    # Should not raise
    await probe._process_provider_batch("test_provider", resources)


# UT-08: callback with correct values after ramp-up
@pytest.mark.asyncio
async def test_ut08_callback_after_ramp_up():
    """After a successful batch, batch_size increases via ramp-up."""
    callback_args = []

    def my_callback(
        provider_name,
        batch_size,
        batch_delay,
        rate_limit_events,
        backoff_events,
        recovery_events,
    ):
        callback_args.append(batch_size)

    probe = _make_probe(on_batch_complete=my_callback)
    probe._check_resource = AsyncMock(return_value=CheckResult.success())
    probe._update_resource_status = AsyncMock()

    # 30 resources, initial batch_size=10 (from _make_probe), so 3+ batches
    resources = [{"key_id": i, "provider_name": "test_provider"} for i in range(30)]
    await probe._process_provider_batch("test_provider", resources)

    # After first batch of 10, ramp-up increases batch_size
    assert len(callback_args) >= 2
    # Second call should have larger batch_size than first
    assert callback_args[1] > callback_args[0]


# UT-09: callback with correct values after rate-limited backoff
@pytest.mark.asyncio
async def test_ut09_callback_after_rate_limited():
    """After a rate-limited batch, rate_limit_events increments and batch shrinks."""
    callback_args = []

    def my_callback(
        provider_name,
        batch_size,
        batch_delay,
        rate_limit_events,
        backoff_events,
        recovery_events,
    ):
        callback_args.append(
            {
                "batch_size": batch_size,
                "rate_limit_events": rate_limit_events,
            }
        )

    policy = HealthPolicyConfig(
        adaptive_batching=AdaptiveBatchingConfig(
            start_batch_size=40,
            start_batch_delay_sec=15.0,
        ),
    )
    mock_accessor = MagicMock()
    mock_accessor.get_keeper_concurrency.return_value = 10
    mock_accessor.get_health_policy.return_value = policy
    mock_db = MagicMock()
    mock_client_factory = MagicMock()
    probe = CallbackTestProbe(
        mock_accessor,
        mock_db,
        mock_client_factory,
        on_batch_complete=my_callback,
    )
    probe._check_resource = AsyncMock(
        return_value=CheckResult.fail(ErrorReason.RATE_LIMITED, "rate limited")
    )
    probe._update_resource_status = AsyncMock()

    resources = [{"key_id": i, "provider_name": "test_provider"} for i in range(40)]
    await probe._process_provider_batch("test_provider", resources)

    assert len(callback_args) >= 1
    last = callback_args[-1]
    # After rate-limited, batch_size should decrease
    assert last["batch_size"] < 40
    assert last["rate_limit_events"] >= 1


# UT-10: callback called on every while-loop iteration
@pytest.mark.asyncio
async def test_ut10_callback_on_every_while_iteration():
    """With 100 resources and batch_size=30, callback fires 3+ times."""
    call_count = 0

    def my_callback(
        provider_name,
        batch_size,
        batch_delay,
        rate_limit_events,
        backoff_events,
        recovery_events,
    ):
        nonlocal call_count
        call_count += 1

    policy = HealthPolicyConfig(
        adaptive_batching=AdaptiveBatchingConfig(
            start_batch_size=30,
            start_batch_delay_sec=15.0,
        ),
    )
    mock_accessor = MagicMock()
    mock_accessor.get_keeper_concurrency.return_value = 10
    mock_accessor.get_health_policy.return_value = policy
    mock_db = MagicMock()
    mock_client_factory = MagicMock()
    probe = CallbackTestProbe(
        mock_accessor,
        mock_db,
        mock_client_factory,
        on_batch_complete=my_callback,
    )
    probe._check_resource = AsyncMock(return_value=CheckResult.success())
    probe._update_resource_status = AsyncMock()

    resources = [{"key_id": i, "provider_name": "test_provider"} for i in range(100)]
    await probe._process_provider_batch("test_provider", resources)

    # 100 resources / ~30 per batch = at least 3, at most 4
    assert 3 <= call_count <= 5, f"Expected 3-5 callbacks, got {call_count}"


# UT-11 removed: duplicate of SEC-01 in test_adaptive_security.py
# (probes.py no-services-import check is consolidated there)
