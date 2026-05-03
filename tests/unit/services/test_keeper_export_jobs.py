"""Tests for APScheduler export job registration in keeper.run_keeper().

Group 8 from test-plan.md: Services — APScheduler jobs (keeper)

Verifies that run_keeper() correctly registers snapshot and inventory export
jobs on the APScheduler based on provider key_export configuration.
"""

from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from apscheduler.triggers.interval import IntervalTrigger

from src.config.schemas import (
    DatabasePoolConfig,
    KeyExportConfig,
    KeyInventoryConfig,
    ProviderConfig,
)
from src.core.constants import Status
from src.services.keeper import run_keeper


def _make_provider(
    enabled: bool = True,
    snapshot_interval_hours: int = 0,
    inventory_enabled: bool = False,
    inventory_interval_minutes: int = 1440,
    inventory_statuses: list[Status] | None = None,
) -> ProviderConfig:
    """Create a ProviderConfig with specific key_export settings."""
    return ProviderConfig(
        provider_type="openai_like",
        enabled=enabled,
        key_export=KeyExportConfig(
            enabled=True,
            snapshot_interval_hours=snapshot_interval_hours,
            inventory=KeyInventoryConfig(
                enabled=inventory_enabled,
                interval_minutes=inventory_interval_minutes,
                statuses=inventory_statuses if inventory_statuses is not None else [],
            ),
        ),
    )


async def _run_keeper_capture_scheduler(
    deps, providers: dict[str, ProviderConfig]
) -> MagicMock:
    """Customize fixture deps with providers and run run_keeper().

    Sets accessor providers, configures scheduler to break via
    KeyboardInterrupt at start(), and sets up the exporter mock.
    Returns the scheduler mock for inspection.
    """
    # Customize accessor with test-specific providers
    deps.accessor.get_all_providers.return_value = providers
    deps.accessor.get_enabled_providers.return_value = {
        k: v for k, v in providers.items() if v.enabled
    }
    deps.accessor.get_pool_config.return_value = DatabasePoolConfig(
        min_size=1, max_size=5
    )

    # Break the infinite sleep loop by raising at scheduler.start()
    deps.scheduler.start.side_effect = KeyboardInterrupt

    # Set up exporter mock (file-specific, not in common fixture)
    mock_exporter = MagicMock()
    mock_exporter.export_snapshot = AsyncMock()
    mock_exporter.export_inventory = AsyncMock()
    deps.key_inventory_exporter.return_value = mock_exporter

    await run_keeper()

    return deps.scheduler


def _export_add_job_calls(scheduler: MagicMock) -> list:
    """Filter scheduler.add_job calls to only snapshot/inventory export jobs."""
    export_calls = []
    for call in scheduler.add_job.call_args_list:
        job_id = call.kwargs.get("id", "")
        if job_id.startswith("snapshot_") or job_id.startswith("inventory_"):
            export_calls.append(call)
    return export_calls


# ── Test cases ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_snapshot_job_added_when_interval_gt_zero(
    mock_run_keeper_dependencies,
):
    """snapshot_interval_hours=24 → scheduler.add_job with IntervalTrigger(hours=24)."""
    providers = {"openai": _make_provider(snapshot_interval_hours=24)}
    scheduler = await _run_keeper_capture_scheduler(
        mock_run_keeper_dependencies, providers
    )

    export_calls = _export_add_job_calls(scheduler)
    assert len(export_calls) == 1

    call = export_calls[0]
    assert call.kwargs["id"] == "snapshot_openai"
    trigger = call.kwargs["trigger"]
    assert isinstance(trigger, IntervalTrigger)
    assert trigger.interval == timedelta(hours=24)


@pytest.mark.asyncio
async def test_no_snapshot_job_when_interval_zero(
    mock_run_keeper_dependencies,
):
    """snapshot_interval_hours=0 → no snapshot job added."""
    providers = {"openai": _make_provider(snapshot_interval_hours=0)}
    scheduler = await _run_keeper_capture_scheduler(
        mock_run_keeper_dependencies, providers
    )

    export_calls = _export_add_job_calls(scheduler)
    snapshot_calls = [
        c for c in export_calls if c.kwargs.get("id", "").startswith("snapshot_")
    ]
    assert len(snapshot_calls) == 0


@pytest.mark.asyncio
async def test_inventory_job_added_when_enabled(
    mock_run_keeper_dependencies,
):
    """inventory.enabled=True, interval_minutes=60 → job with IntervalTrigger(minutes=60)."""
    providers = {
        "openai": _make_provider(
            inventory_enabled=True,
            inventory_interval_minutes=60,
            inventory_statuses=[Status.VALID],
        )
    }
    scheduler = await _run_keeper_capture_scheduler(
        mock_run_keeper_dependencies, providers
    )

    export_calls = _export_add_job_calls(scheduler)
    inventory_calls = [
        c for c in export_calls if c.kwargs.get("id", "").startswith("inventory_")
    ]
    assert len(inventory_calls) == 1

    call = inventory_calls[0]
    trigger = call.kwargs["trigger"]
    assert isinstance(trigger, IntervalTrigger)
    assert trigger.interval == timedelta(minutes=60)


@pytest.mark.asyncio
async def test_no_inventory_job_when_disabled(
    mock_run_keeper_dependencies,
):
    """inventory.enabled=False → no inventory job added."""
    providers = {"openai": _make_provider(inventory_enabled=False)}
    scheduler = await _run_keeper_capture_scheduler(
        mock_run_keeper_dependencies, providers
    )

    export_calls = _export_add_job_calls(scheduler)
    inventory_calls = [
        c for c in export_calls if c.kwargs.get("id", "").startswith("inventory_")
    ]
    assert len(inventory_calls) == 0


@pytest.mark.asyncio
async def test_both_jobs_added_when_both_enabled(
    mock_run_keeper_dependencies,
):
    """Both snapshot and inventory enabled → two export jobs added."""
    providers = {
        "openai": _make_provider(
            snapshot_interval_hours=24,
            inventory_enabled=True,
            inventory_interval_minutes=60,
            inventory_statuses=[Status.VALID],
        )
    }
    scheduler = await _run_keeper_capture_scheduler(
        mock_run_keeper_dependencies, providers
    )

    export_calls = _export_add_job_calls(scheduler)
    assert len(export_calls) == 2

    ids = [c.kwargs["id"] for c in export_calls]
    assert "snapshot_openai" in ids
    assert "inventory_openai" in ids


@pytest.mark.asyncio
async def test_export_jobs_not_added_for_disabled_provider(
    mock_run_keeper_dependencies,
):
    """provider.enabled=False → no export jobs added for that provider."""
    providers = {
        "disabled_provider": _make_provider(
            enabled=False,
            snapshot_interval_hours=24,
            inventory_enabled=True,
            inventory_statuses=[Status.VALID],
        )
    }
    scheduler = await _run_keeper_capture_scheduler(
        mock_run_keeper_dependencies, providers
    )

    export_calls = _export_add_job_calls(scheduler)
    assert len(export_calls) == 0


@pytest.mark.asyncio
async def test_snapshot_job_id_includes_provider_name(
    mock_run_keeper_dependencies,
):
    """Snapshot job_id format includes provider name for uniqueness."""
    providers = {"my_special_provider": _make_provider(snapshot_interval_hours=12)}
    scheduler = await _run_keeper_capture_scheduler(
        mock_run_keeper_dependencies, providers
    )

    export_calls = _export_add_job_calls(scheduler)
    assert len(export_calls) == 1
    assert export_calls[0].kwargs["id"] == "snapshot_my_special_provider"


@pytest.mark.asyncio
async def test_inventory_job_id_includes_provider_name(
    mock_run_keeper_dependencies,
):
    """Inventory job_id format includes provider name for uniqueness."""
    providers = {
        "my_special_provider": _make_provider(
            inventory_enabled=True,
            inventory_interval_minutes=30,
            inventory_statuses=[Status.VALID, Status.NO_QUOTA],
        )
    }
    scheduler = await _run_keeper_capture_scheduler(
        mock_run_keeper_dependencies, providers
    )

    export_calls = _export_add_job_calls(scheduler)
    inventory_calls = [
        c for c in export_calls if c.kwargs.get("id", "").startswith("inventory_")
    ]
    assert len(inventory_calls) == 1
    assert inventory_calls[0].kwargs["id"] == "inventory_my_special_provider"