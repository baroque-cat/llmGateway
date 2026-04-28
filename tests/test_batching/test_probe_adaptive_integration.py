#!/usr/bin/env python3

"""
Integration tests for IResourceProbe._process_provider_batch with AdaptiveBatchController.

Covers scenarios IC-01 through IC-17 from the adaptive-batching test plan:
while-loop iteration, dynamic batch_size/batch_delay, CheckResult | None return,
gather filtering, error classification, controller persistence, full-cycle
trajectories, edge cases, semaphore integration, run_cycle compatibility,
multi-provider independence, and timeout wrapper behaviour.
"""

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.config.schemas import AdaptiveBatchingConfig, HealthPolicyConfig
from src.core.batching import AdaptiveBatchController
from src.core.constants import ErrorReason
from src.core.models import CheckResult
from src.core.probes import IResourceProbe


# ----------------------------------------------------------------------
# Concrete Test Probe — reusable across all scenarios
# ----------------------------------------------------------------------
class ConcreteTestProbe(IResourceProbe):
    """
    Minimal concrete subclass of IResourceProbe for integration testing.
    Abstract methods are overridden with simple defaults; tests can
    replace them with AsyncMock or custom logic as needed.
    """

    async def _get_resources_to_check(self) -> list[dict[str, Any]]:
        return []

    async def _check_resource(self, resource: dict[str, Any]) -> CheckResult:
        return CheckResult.success()

    async def _update_resource_status(
        self, resource: dict[str, Any], result: CheckResult
    ) -> None:
        pass


# ----------------------------------------------------------------------
# Helper: build a list of resource dicts
# ----------------------------------------------------------------------
def _make_resources(
    count: int, provider_name: str = "test_provider"
) -> list[dict[str, Any]]:
    """Create *count* resource dicts with sequential key_id values."""
    return [{"key_id": i, "provider_name": provider_name} for i in range(count)]


# ----------------------------------------------------------------------
# Helper: create a probe with mocked dependencies
# ----------------------------------------------------------------------
def _make_probe(
    policy: HealthPolicyConfig | None = None,
    concurrency: int = 10,
    on_batch_complete=None,
) -> ConcreteTestProbe:
    """
    Build a ConcreteTestProbe with mocked accessor, db_manager, client_factory.

    The accessor's get_health_policy returns *policy* for any provider name.
    """
    mock_accessor = MagicMock()
    mock_accessor.get_worker_concurrency.return_value = concurrency
    mock_accessor.get_health_policy.return_value = policy
    mock_db = MagicMock()
    mock_client_factory = MagicMock()
    return ConcreteTestProbe(
        mock_accessor, mock_db, mock_client_factory, on_batch_complete=on_batch_complete
    )


# ----------------------------------------------------------------------
# Helper: default policy with adaptive batching
# ----------------------------------------------------------------------
def _default_policy(
    start_batch_size: int = 30,
    start_batch_delay_sec: float = 15.0,
    adaptive: AdaptiveBatchingConfig | None = None,
) -> HealthPolicyConfig:
    """Return a HealthPolicyConfig with sensible defaults for testing.

    Initial batch values are now set via AdaptiveBatchingConfig
    (start_batch_size / start_batch_delay_sec), not via HealthPolicyConfig
    batch_size / batch_delay_sec (those fields were removed).
    """
    if adaptive is None:
        adaptive = AdaptiveBatchingConfig(
            start_batch_size=start_batch_size,
            start_batch_delay_sec=start_batch_delay_sec,
        )
    return HealthPolicyConfig(
        adaptive_batching=adaptive,
    )


# ======================================================================
# IC-01: While-loop replaces for-loop — batch partitioning
# ======================================================================
@pytest.mark.asyncio
async def test_ic01_while_loop_replaces_for_loop():
    """
    100 resources, initial_batch_size=30.
    _process_provider_batch should iterate in 4 sub-batches:
    30, 30, 30, 10.  The while i < len(resources) loop advances
    correctly and the controller receives each batch's results.
    """
    policy = _default_policy()
    probe = _make_probe(policy=policy)

    resources = _make_resources(100)

    # Track which resources are checked and in what order
    checked_resources: list[dict[str, Any]] = []

    async def mock_check(res: dict[str, Any]) -> CheckResult:
        checked_resources.append(res)
        return CheckResult.success()

    probe._check_resource = AsyncMock(side_effect=mock_check)
    probe._update_resource_status = AsyncMock()

    await probe._process_provider_batch("test_provider", resources)

    # All 100 resources were checked
    assert len(checked_resources) == 100

    # Verify batch boundaries: the controller was created with batch_size=30
    controller = probe._batch_controllers["test_provider"]
    assert controller is not None

    # The while-loop uses dynamically updated batch_size after each batch.
    # Batch 1: 30 resources (i=0→30), success → batch_size=35, delay=13
    # Batch 2: 35 resources (i=30→65), success → batch_size=40, delay=11
    # Batch 3: 35 resources (i=65→100), success → batch_size=45, delay=9
    # Only 3 batches because the adaptive ramp-up consumed remaining resources
    # faster than a fixed for-loop would have.
    assert controller.consecutive_successes == 3
    assert controller.batch_size == 45  # 30 + 5, then 35+5, then 40+5 = 45
    assert controller.batch_delay == 9.0  # 15-2, then 13-2, then 11-2 = 9.0


# ======================================================================
# IC-02: While-loop — batch_size changes between batches
# ======================================================================
@pytest.mark.asyncio
async def test_ic02_batch_size_changes_between_batches():
    """
    After the first successful batch, batch_size increases (30→35).
    The second batch should use the new batch_size=35.
    This is the key difference from a for-loop with fixed step.
    """
    # Use a small max so ramp-up is visible
    adaptive = AdaptiveBatchingConfig(
        start_batch_size=30,
        start_batch_delay_sec=15.0,
        min_batch_size=5,
        max_batch_size=100,
        min_batch_delay_sec=1.0,
        max_batch_delay_sec=120.0,
        batch_size_step=10,
        delay_step_sec=2.0,
    )
    policy = _default_policy(adaptive=adaptive)
    probe = _make_probe(policy=policy)

    # 65 resources: first batch 30, second batch 40 (30+10), last batch 5 (65-30-40=5)
    # Wait — after first batch success, batch_size becomes 30+10=40
    # So second batch is resources[30:70] = 35 resources (only 35 left)
    # Actually we need enough resources so the second batch is clearly different
    resources = _make_resources(75)  # 30 + 40 + 5

    batch_sizes_seen: list[int] = []

    original_check = probe._check_resource

    async def tracking_check(res: dict[str, Any]) -> CheckResult:
        return CheckResult.success()

    probe._check_resource = AsyncMock(side_effect=tracking_check)
    probe._update_resource_status = AsyncMock()

    # We need to observe the batch_size used for each sub-batch.
    # Patch the while-loop body to record batch_size at each iteration.
    # Instead, we can infer from the controller state after processing.
    await probe._process_provider_batch("test_provider", resources)

    controller = probe._batch_controllers["test_provider"]

    # First batch: 30 resources, success → batch_size += 10 = 40
    # Second batch: 40 resources (resources[30:70]), success → batch_size += 10 = 50
    # Third batch: 5 resources (resources[70:75]), success → batch_size += 10 = 60
    # 3 consecutive successes
    assert controller.consecutive_successes == 3
    # batch_size after 3 ramp-ups: 30 + 3*10 = 60
    assert controller.batch_size == 60


# ======================================================================
# IC-03: While-loop — batch_delay changes between batches
# ======================================================================
@pytest.mark.asyncio
async def test_ic03_batch_delay_changes_between_batches():
    """
    After the first successful batch, batch_delay decreases (15→13).
    asyncio.sleep between batches should use the new delay.
    """
    policy = _default_policy()
    probe = _make_probe(policy=policy)

    # 60 resources: first batch 30, second batch 30
    resources = _make_resources(60)

    probe._check_resource = AsyncMock(return_value=CheckResult.success())
    probe._update_resource_status = AsyncMock()

    sleep_calls: list[float] = []

    with patch(
        "asyncio.sleep", new=AsyncMock(side_effect=lambda s: sleep_calls.append(s))
    ):
        await probe._process_provider_batch("test_provider", resources)

    # First batch success → delay goes from 15 → 13.0 (15 - 2.0)
    # Sleep between batch 1 and batch 2 should use the NEW delay (13.0)
    assert len(sleep_calls) == 1  # Only one sleep between two batches
    assert sleep_calls[0] == 13.0  # Updated delay after first batch success


# ======================================================================
# IC-04: _check_and_update_resource returns CheckResult | None
# ======================================================================
@pytest.mark.asyncio
async def test_ic04_check_and_update_resource_returns_checkresult_or_none():
    """
    _check_and_update_resource should return CheckResult on success
    and None when an exception is caught.
    """
    policy = _default_policy()
    probe = _make_probe(policy=policy)

    # Case 1: Normal execution → returns CheckResult
    probe._check_resource = AsyncMock(return_value=CheckResult.success())
    probe._update_resource_status = AsyncMock()

    result = await probe._check_and_update_resource({"key_id": 1})
    assert isinstance(result, CheckResult)
    assert result.available is True

    # Case 2: Exception in _check_resource → returns None
    probe._check_resource = AsyncMock(side_effect=RuntimeError("boom"))

    result = await probe._check_and_update_resource({"key_id": 2})
    assert result is None


# ======================================================================
# IC-05: Filtering gather results — isinstance(r, CheckResult)
# ======================================================================
@pytest.mark.asyncio
async def test_ic05_filtering_gather_results_isinstance_checkresult():
    """
    After gather, None values (from exceptions) are excluded.
    Only CheckResult objects are passed to controller.report_batch_result.
    """
    policy = _default_policy(start_batch_size=10, start_batch_delay_sec=5.0)
    probe = _make_probe(policy=policy)

    resources = _make_resources(10)

    # Mix of success and exception results
    call_count = 0

    async def mixed_check(res: dict[str, Any]) -> CheckResult:
        return CheckResult.success()

    # Make _check_and_update_resource return None for some resources
    original_method = probe._check_and_update_resource

    results_from_method: list[CheckResult | None] = []

    async def patched_check_and_update(res: dict[str, Any]) -> CheckResult | None:
        idx = res["key_id"]
        if idx % 3 == 0:  # keys 0, 3, 6, 9 → exception → None
            return None
        return CheckResult.success()

    probe._check_and_update_resource = AsyncMock(side_effect=patched_check_and_update)

    # We need to verify that the controller only receives CheckResult objects.
    # Patch report_batch_result to capture what it receives.
    reported_results: list[CheckResult] = []

    controller = AdaptiveBatchController(
        config=policy.adaptive_batching,
    )

    original_report = controller.report_batch_result

    def capturing_report(results: list[CheckResult]) -> None:
        reported_results.extend(results)
        original_report(results)

    controller.report_batch_result = capturing_report

    # Pre-populate the controller so _process_provider_batch uses it
    probe._batch_controllers["test_provider"] = controller

    await probe._process_provider_batch("test_provider", resources)

    # 10 resources, 4 of which return None (key_id 0, 3, 6, 9)
    # Only 6 CheckResult objects should have been reported
    assert len(reported_results) == 6
    assert all(isinstance(r, CheckResult) for r in reported_results)
    assert all(r is not None for r in reported_results)


# ======================================================================
# IC-06: Classification of CheckResult by ErrorReason
# ======================================================================
@pytest.mark.asyncio
async def test_ic06_classification_of_checkresult_by_error_reason():
    """
    Probe counts fatal, transient, rate_limited from results.
    Verify correct counting of each category.
    """
    policy = _default_policy(start_batch_size=10, start_batch_delay_sec=5.0)
    probe = _make_probe(policy=policy)

    resources = _make_resources(10)

    # Create a mix of error reasons:
    # 2 fatal (INVALID_KEY), 3 transient (TIMEOUT), 1 rate_limited, 4 success
    error_map: dict[int, CheckResult] = {
        0: CheckResult.fail(ErrorReason.INVALID_KEY),
        1: CheckResult.fail(ErrorReason.INVALID_KEY),
        2: CheckResult.fail(ErrorReason.TIMEOUT),
        3: CheckResult.fail(ErrorReason.TIMEOUT),
        4: CheckResult.fail(ErrorReason.TIMEOUT),
        5: CheckResult.fail(ErrorReason.RATE_LIMITED),
        6: CheckResult.success(),
        7: CheckResult.success(),
        8: CheckResult.success(),
        9: CheckResult.success(),
    }

    async def classified_check(res: dict[str, Any]) -> CheckResult:
        return error_map[res["key_id"]]

    probe._check_and_update_resource = AsyncMock(side_effect=classified_check)

    reported_results: list[CheckResult] = []

    controller = AdaptiveBatchController(
        config=policy.adaptive_batching,
    )

    original_report = controller.report_batch_result

    def capturing_report(results: list[CheckResult]) -> None:
        reported_results.extend(results)
        original_report(results)

    controller.report_batch_result = capturing_report
    probe._batch_controllers["test_provider"] = controller

    await probe._process_provider_batch("test_provider", resources)

    # All 10 results should be reported (no exceptions/None)
    assert len(reported_results) == 10

    # Verify classification counts
    fatal_count = sum(1 for r in reported_results if r.error_reason.is_fatal())
    rate_limited_count = sum(
        1 for r in reported_results if r.error_reason == ErrorReason.RATE_LIMITED
    )
    transient_count = sum(
        1
        for r in reported_results
        if r.error_reason.is_retryable()
        and not r.error_reason.is_fatal()
        and r.error_reason != ErrorReason.RATE_LIMITED
    )

    assert fatal_count == 2
    assert rate_limited_count == 1
    assert transient_count == 3

    # With rate_limited present, aggressive backoff should have been applied
    # batch_size //= 2 → 10 // 2 = 5
    assert controller.batch_size == 5
    # batch_delay *= 2 → 5.0 * 2 = 10.0
    assert controller.batch_delay == 10.0


# ======================================================================
# IC-07: _batch_controllers dict per provider — lazy creation & reuse
# ======================================================================
@pytest.mark.asyncio
async def test_ic07_batch_controllers_dict_per_provider():
    """
    Controller is created on first call to _process_provider_batch,
    reused on second call, and state persists between calls.
    """
    policy = _default_policy(start_batch_size=10, start_batch_delay_sec=5.0)
    probe = _make_probe(policy=policy)

    resources_batch1 = _make_resources(10)
    resources_batch2 = _make_resources(10)

    probe._check_and_update_resource = AsyncMock(return_value=CheckResult.success())

    # First call — controller should be created
    await probe._process_provider_batch("test_provider", resources_batch1)

    assert "test_provider" in probe._batch_controllers
    controller_after_first = probe._batch_controllers["test_provider"]

    # After first successful batch: batch_size = 10+5=15, consecutive_successes=1
    assert controller_after_first.batch_size == 15
    assert controller_after_first.consecutive_successes == 1

    # Second call — same controller should be reused (not replaced)
    await probe._process_provider_batch("test_provider", resources_batch2)

    controller_after_second = probe._batch_controllers["test_provider"]

    # Same object — state persisted
    assert controller_after_second is controller_after_first
    # Second success: consecutive_successes=2, batch_size=15+5=20
    assert controller_after_second.consecutive_successes == 2
    assert controller_after_second.batch_size == 20


# ======================================================================
# IC-08: Full cycle — success → ramp-up → rate_limited → backoff → recovery
# ======================================================================
@pytest.mark.asyncio
async def test_ic08_full_cycle_success_rampup_rate_limited_backoff_recovery():
    """
    Synthetic scenario:
    - 3 successful batches (batch_size grows)
    - 1 rate_limited batch (aggressive backoff)
    - 2 successful batches (moderate ramp-up)
    Verify batch_size and batch_delay follow expected trajectory.
    """
    adaptive = AdaptiveBatchingConfig(
        start_batch_size=30,
        start_batch_delay_sec=15.0,
        min_batch_size=5,
        max_batch_size=50,
        min_batch_delay_sec=3.0,
        max_batch_delay_sec=120.0,
        batch_size_step=5,
        delay_step_sec=2.0,
        rate_limit_divisor=2,
        rate_limit_delay_multiplier=2.0,
    )
    policy = _default_policy(adaptive=adaptive)
    probe = _make_probe(policy=policy)

    controller = AdaptiveBatchController(
        config=adaptive,
    )
    probe._batch_controllers["test_provider"] = controller

    # --- Phase 1: 3 successful batches ---
    success_results = [CheckResult.success() for _ in range(10)]
    controller.report_batch_result(success_results)
    # batch_size: 30 + 5 = 35, delay: 15 - 2 = 13, consecutive: 1
    assert controller.batch_size == 35
    assert controller.batch_delay == 13.0

    controller.report_batch_result(success_results)
    # batch_size: 35 + 5 = 40, delay: 13 - 2 = 11, consecutive: 2
    assert controller.batch_size == 40
    assert controller.batch_delay == 11.0

    controller.report_batch_result(success_results)
    # batch_size: 40 + 5 = 45, delay: 11 - 2 = 9, consecutive: 3
    assert controller.batch_size == 45
    assert controller.batch_delay == 9.0

    # --- Phase 2: 1 rate_limited batch ---
    rate_limited_results = [CheckResult.fail(ErrorReason.RATE_LIMITED)]
    controller.report_batch_result(rate_limited_results)
    # batch_size: 45 // 2 = 22, delay: 9 * 2 = 18, consecutive: 0
    assert controller.batch_size == 22
    assert controller.batch_delay == 18.0
    assert controller.consecutive_successes == 0

    # --- Phase 3: 2 successful batches (moderate ramp-up) ---
    controller.report_batch_result(success_results)
    # batch_size: 22 + 5 = 27, delay: 18 - 2 = 16, consecutive: 1
    assert controller.batch_size == 27
    assert controller.batch_delay == 16.0

    controller.report_batch_result(success_results)
    # batch_size: 27 + 5 = 32, delay: 16 - 2 = 14, consecutive: 2
    assert controller.batch_size == 32
    assert controller.batch_delay == 14.0


# ======================================================================
# IC-09: Full cycle — mixed results in one batch
# ======================================================================
@pytest.mark.asyncio
async def test_ic09_mixed_results_in_one_batch():
    """
    Batch with 10: 2 fatal (INVALID_KEY), 3 transient (TIMEOUT),
    1 rate_limited, 4 success.
    Fatal excluded from failure rate, rate_limited has priority →
    aggressive backoff applied.
    """
    adaptive = AdaptiveBatchingConfig(
        start_batch_size=30,
        start_batch_delay_sec=15.0,
        min_batch_size=5,
        max_batch_size=50,
        min_batch_delay_sec=3.0,
        max_batch_delay_sec=120.0,
        batch_size_step=5,
        delay_step_sec=2.0,
    )
    policy = _default_policy(adaptive=adaptive)
    probe = _make_probe(policy=policy)

    controller = AdaptiveBatchController(
        config=adaptive,
    )

    mixed_results: list[CheckResult] = [
        CheckResult.fail(ErrorReason.INVALID_KEY),  # fatal
        CheckResult.fail(ErrorReason.INVALID_KEY),  # fatal
        CheckResult.fail(ErrorReason.TIMEOUT),  # transient
        CheckResult.fail(ErrorReason.TIMEOUT),  # transient
        CheckResult.fail(ErrorReason.TIMEOUT),  # transient
        CheckResult.fail(ErrorReason.RATE_LIMITED),  # rate_limited
        CheckResult.success(),  # success
        CheckResult.success(),  # success
        CheckResult.success(),  # success
        CheckResult.success(),  # success
    ]

    controller.report_batch_result(mixed_results)

    # rate_limited present → aggressive backoff (priority over transient)
    # batch_size //= 2 → 30 // 2 = 15
    assert controller.batch_size == 15
    # batch_delay *= 2 → 15.0 * 2 = 30.0
    assert controller.batch_delay == 30.0
    # consecutive_successes reset to 0
    assert controller.consecutive_successes == 0


# ======================================================================
# IC-10: _process_provider_batch — no policy (None)
# ======================================================================
@pytest.mark.asyncio
async def test_ic10_no_policy_none():
    """
    accessor.get_health_policy returns None.
    Probe should skip processing — no controller created, no resources checked.
    """
    probe = _make_probe(policy=None)  # accessor returns None

    resources = _make_resources(10)
    probe._check_and_update_resource = AsyncMock(return_value=CheckResult.success())

    await probe._process_provider_batch("test_provider", resources)

    # No controller should have been created
    assert "test_provider" not in probe._batch_controllers
    # No resources should have been checked
    probe._check_and_update_resource.assert_not_called()


# ======================================================================
# IC-11: _process_provider_batch — adaptive_batching absent in config
# ======================================================================
@pytest.mark.asyncio
async def test_ic11_adaptive_batching_absent_uses_default_factory():
    """
    HealthPolicyConfig without explicit adaptive_batching uses default_factory.
    Controller should be created with default initial values from AdaptiveBatchingConfig
    (start_batch_size=30, start_batch_delay_sec=15.0).
    """
    # Create policy without specifying adaptive_batching — default_factory kicks in
    policy = HealthPolicyConfig()
    probe = _make_probe(policy=policy)

    resources = _make_resources(30)
    probe._check_and_update_resource = AsyncMock(return_value=CheckResult.success())

    await probe._process_provider_batch("test_provider", resources)

    controller = probe._batch_controllers["test_provider"]
    assert controller is not None

    # Controller initial values come from AdaptiveBatchingConfig defaults:
    # start_batch_size=30, start_batch_delay_sec=15.0
    # min_batch_size=5, max_batch_size=50
    # min_batch_delay_sec=3.0, max_batch_delay_sec=120.0
    assert policy.adaptive_batching.start_batch_size == 30
    assert policy.adaptive_batching.start_batch_delay_sec == 15.0
    assert policy.adaptive_batching.min_batch_size == 5
    assert policy.adaptive_batching.max_batch_size == 50

    # After one successful batch of 30, controller ramps up:
    # batch_size: 30 + 5 = 35, batch_delay: 15.0 - 2.0 = 13.0
    assert controller.batch_size == 35
    assert controller.batch_delay == 13.0


# ======================================================================
# IC-12: Edge — empty resource list
# ======================================================================
@pytest.mark.asyncio
async def test_ic12_empty_resource_list():
    """
    _process_provider_batch(provider, []).
    While-loop doesn't execute. No-op — controller not called for reporting.
    """
    policy = _default_policy()
    probe = _make_probe(policy=policy)

    probe._check_and_update_resource = AsyncMock(return_value=CheckResult.success())

    await probe._process_provider_batch("test_provider", [])

    # Controller should be created (lazy init happens before the while-loop)
    assert "test_provider" in probe._batch_controllers
    controller = probe._batch_controllers["test_provider"]

    # But no resources were checked
    probe._check_and_update_resource.assert_not_called()

    # Controller state should remain at initial values (no report_batch_result called)
    assert controller.batch_size == 30
    assert controller.batch_delay == 15.0
    assert controller.consecutive_successes == 0


# ======================================================================
# IC-13: Edge — 1 resource
# ======================================================================
@pytest.mark.asyncio
async def test_ic13_one_resource():
    """
    _process_provider_batch(provider, [resource]).
    One batch, one resource. Controller receives total=1.
    """
    policy = _default_policy()
    probe = _make_probe(policy=policy)

    resources = _make_resources(1)
    probe._check_and_update_resource = AsyncMock(return_value=CheckResult.success())

    reported_results: list[CheckResult] = []

    controller = AdaptiveBatchController(
        config=policy.adaptive_batching,
    )

    original_report = controller.report_batch_result

    def capturing_report(results: list[CheckResult]) -> None:
        reported_results.extend(results)
        original_report(results)

    controller.report_batch_result = capturing_report
    probe._batch_controllers["test_provider"] = controller

    await probe._process_provider_batch("test_provider", resources)

    # One CheckResult reported
    assert len(reported_results) == 1
    assert reported_results[0].available is True

    # Controller ramp-up: 30 + 5 = 35
    assert controller.batch_size == 35
    assert controller.consecutive_successes == 1


# ======================================================================
# IC-14: Semaphore integration
# ======================================================================
@pytest.mark.asyncio
async def test_ic14_semaphore_integration():
    """
    _process_provider_batch works inside async with self.semaphore.
    Verify semaphore doesn't block while-loop between batches.
    """
    policy = _default_policy()
    probe = _make_probe(policy=policy, concurrency=5)

    resources = _make_resources(60)

    probe._check_and_update_resource = AsyncMock(return_value=CheckResult.success())

    # The semaphore has capacity 5. _process_provider_batch acquires it once
    # for the entire method, so the while-loop should not be blocked between
    # batches. We verify by checking that all resources were processed.
    with patch("asyncio.sleep", new=AsyncMock()):
        await probe._process_provider_batch("test_provider", resources)

    # All 60 resources should have been checked
    assert probe._check_and_update_resource.call_count == 60

    # Controller should show 2 successful batches (30 + 30)
    controller = probe._batch_controllers["test_provider"]
    assert controller.consecutive_successes == 2


# ======================================================================
# IC-15: run_cycle() compatible with _batch_controllers
# ======================================================================
@pytest.mark.asyncio
async def test_ic15_run_cycle_compatible_with_batch_controllers():
    """
    After run_cycle(), _batch_controllers populated.
    active_tasks cleanup doesn't affect _batch_controllers.
    """
    policy = _default_policy(start_batch_size=10, start_batch_delay_sec=5.0)
    probe = _make_probe(policy=policy)

    resources = _make_resources(10, provider_name="openai")
    probe._get_resources_to_check = AsyncMock(return_value=resources)
    probe._check_and_update_resource = AsyncMock(return_value=CheckResult.success())

    await probe.run_cycle()

    # Wait for the task to complete
    if "openai" in probe.active_tasks:
        await probe.active_tasks["openai"]
    await asyncio.sleep(0.05)

    # active_tasks should be cleaned up
    assert "openai" not in probe.active_tasks

    # But _batch_controllers should persist
    assert "openai" in probe._batch_controllers
    controller = probe._batch_controllers["openai"]
    assert controller is not None
    assert controller.consecutive_successes == 1


# ======================================================================
# IC-16: Multiple providers — separate controllers
# ======================================================================
@pytest.mark.asyncio
async def test_ic16_multiple_providers_separate_controllers():
    """
    Two providers (openai, gemini) with different configs.
    _batch_controllers["openai"] and _batch_controllers["gemini"]
    are independent instances with different states.
    """
    # openai: start_batch_size=30, start_batch_delay_sec=15.0
    policy_openai = _default_policy(start_batch_size=30, start_batch_delay_sec=15.0)
    # gemini: start_batch_size=10, start_batch_delay_sec=30.0
    policy_gemini = _default_policy(start_batch_size=10, start_batch_delay_sec=30.0)

    mock_accessor = MagicMock()
    mock_accessor.get_worker_concurrency.return_value = 10

    def get_policy(name: str) -> HealthPolicyConfig | None:
        if name == "openai":
            return policy_openai
        if name == "gemini":
            return policy_gemini
        return None

    mock_accessor.get_health_policy.side_effect = get_policy

    mock_db = MagicMock()
    mock_client_factory = MagicMock()
    probe = ConcreteTestProbe(mock_accessor, mock_db, mock_client_factory)

    probe._check_and_update_resource = AsyncMock(return_value=CheckResult.success())

    openai_resources = _make_resources(30, provider_name="openai")
    gemini_resources = _make_resources(10, provider_name="gemini")

    await probe._process_provider_batch("openai", openai_resources)
    await probe._process_provider_batch("gemini", gemini_resources)

    # Two separate controllers
    assert len(probe._batch_controllers) == 2
    controller_openai = probe._batch_controllers["openai"]
    controller_gemini = probe._batch_controllers["gemini"]

    # They are different objects
    assert controller_openai is not controller_gemini

    # openai: 1 success → batch_size 30+5=35, delay 15-2=13
    assert controller_openai.batch_size == 35
    assert controller_openai.batch_delay == 13.0

    # gemini: 1 success → batch_size 10+5=15, delay 30-2=28
    assert controller_gemini.batch_size == 15
    assert controller_gemini.batch_delay == 28.0


# ======================================================================
# IC-17: Timeout wrapper — _process_provider_batch with adaptive
# ======================================================================
@pytest.mark.asyncio
async def test_ic17_timeout_wrapper_partial_batch_not_reported_on_timeout():
    """
    _run_task_wrapper timeout works correctly with while-loop.
    When timeout interrupts _process_provider_batch, the controller
    state should not be corrupted — partial batch results that were
    already reported remain, but the incomplete batch is not reported.
    """
    # Use a timeout long enough for the first batch to complete but short
    # enough that the second batch (with sleep between batches) is interrupted.
    # First batch of 30 resources completes quickly.
    # Then asyncio.sleep(batch_delay) between batches triggers the timeout.
    policy = HealthPolicyConfig(
        adaptive_batching=AdaptiveBatchingConfig(
            start_batch_size=30,
            start_batch_delay_sec=15.0,
        ),
        task_timeout_sec=2,  # 2 seconds — enough for first batch, not for sleep+second
    )
    probe = _make_probe(policy=policy)

    resources = _make_resources(90)

    probe._check_and_update_resource = AsyncMock(return_value=CheckResult.success())

    # Patch asyncio.sleep to sleep for real (so timeout triggers during inter-batch delay)
    await probe._run_task_wrapper("test_provider", resources)

    # The first batch of 30 should have completed and been reported to the controller.
    # The timeout interrupts during the sleep between batch 1 and batch 2.
    controller = probe._batch_controllers.get("test_provider")
    if controller is not None:
        # First batch completed → consecutive_successes = 1, batch_size ramped up
        # The key point: controller state is not corrupted — it reflects
        # only what was fully reported before the timeout.
        assert controller.consecutive_successes == 1
        assert controller.batch_size == 35  # 30 + 5 = 35 after one success

    # active_tasks should be cleaned up by _run_task_wrapper's finally block
    assert "test_provider" not in probe.active_tasks

    # Not all 90 resources were checked (timeout interrupted after first batch)
    assert probe._check_and_update_resource.call_count < 90


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
