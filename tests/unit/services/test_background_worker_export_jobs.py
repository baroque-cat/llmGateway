"""Tests for APScheduler export job registration in background_worker.run_worker().

Group 8 from test-plan.md: Services — APScheduler jobs (background_worker)

Verifies that run_worker() correctly registers snapshot and inventory export
jobs on the APScheduler based on provider key_export configuration.
"""

from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from apscheduler.triggers.interval import IntervalTrigger

from src.config.schemas import (
    DatabasePoolConfig,
    KeyExportConfig,
    KeyInventoryConfig,
    ProviderConfig,
)
from src.core.constants import Status


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


async def _run_worker_capture_scheduler(
    providers: dict[str, ProviderConfig],
) -> MagicMock:
    """Run run_worker() with all deps mocked; return the scheduler mock for inspection.

    Mocks all infrastructure (config, DB, HTTP, probes, syncers) so that
    run_worker() reaches the export-job registration section.  Breaks execution
    at scheduler.start() via KeyboardInterrupt to avoid the infinite sleep loop.
    """
    mock_accessor = MagicMock()
    mock_accessor.get_all_providers.return_value = providers
    mock_accessor.get_enabled_providers.return_value = {
        k: v for k, v in providers.items() if v.enabled
    }
    mock_accessor.get_database_dsn.return_value = (
        "postgresql://test:test@localhost/testdb"
    )
    mock_accessor.get_pool_config.return_value = DatabasePoolConfig(
        min_size=1, max_size=5
    )

    mock_scheduler = MagicMock()
    mock_scheduler.running = True
    # Break the infinite sleep loop by raising at scheduler.start()
    mock_scheduler.start.side_effect = KeyboardInterrupt

    mock_db_manager = MagicMock()
    mock_db_manager.initialize_schema = AsyncMock()
    mock_db_manager.providers = MagicMock()
    mock_db_manager.providers.sync = AsyncMock()

    mock_client_factory = MagicMock()
    mock_client_factory.close_all = AsyncMock()

    mock_exporter = MagicMock()
    mock_exporter.export_snapshot = AsyncMock()
    mock_exporter.export_inventory = AsyncMock()

    with (
        patch(
            "src.services.background_worker.load_config",
            return_value=MagicMock(),
        ),
        patch(
            "src.services.background_worker.ConfigAccessor",
            return_value=mock_accessor,
        ),
        patch("src.services.background_worker.setup_logging"),
        patch("src.services.background_worker._setup_directories"),
        patch(
            "src.services.background_worker.database.init_db_pool",
            new_callable=AsyncMock,
        ),
        patch(
            "src.services.background_worker.database.close_db_pool",
            new_callable=AsyncMock,
        ),
        patch(
            "src.services.background_worker.DatabaseManager",
            return_value=mock_db_manager,
        ),
        patch(
            "src.services.background_worker.HttpClientFactory",
            return_value=mock_client_factory,
        ),
        patch(
            "src.services.background_worker.get_all_syncers",
            return_value=[],
        ),
        patch(
            "src.services.background_worker.run_sync_cycle",
            new_callable=AsyncMock,
        ),
        patch(
            "src.services.background_worker.get_all_probes",
            return_value=[],
        ),
        patch(
            "src.services.background_worker.AsyncIOScheduler",
            return_value=mock_scheduler,
        ),
        patch(
            "src.services.background_worker.KeyInventoryExporter",
            return_value=mock_exporter,
        ),
    ):
        from src.services.background_worker import run_worker

        await run_worker()

    return mock_scheduler


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
async def test_snapshot_job_added_when_interval_gt_zero():
    """snapshot_interval_hours=24 → scheduler.add_job with IntervalTrigger(hours=24)."""
    providers = {"openai": _make_provider(snapshot_interval_hours=24)}
    scheduler = await _run_worker_capture_scheduler(providers)

    export_calls = _export_add_job_calls(scheduler)
    assert len(export_calls) == 1

    call = export_calls[0]
    assert call.kwargs["id"] == "snapshot_openai"
    trigger = call.kwargs["trigger"]
    assert isinstance(trigger, IntervalTrigger)
    assert trigger.interval == timedelta(hours=24)


@pytest.mark.asyncio
async def test_no_snapshot_job_when_interval_zero():
    """snapshot_interval_hours=0 → no snapshot job added."""
    providers = {"openai": _make_provider(snapshot_interval_hours=0)}
    scheduler = await _run_worker_capture_scheduler(providers)

    export_calls = _export_add_job_calls(scheduler)
    snapshot_calls = [
        c for c in export_calls if c.kwargs.get("id", "").startswith("snapshot_")
    ]
    assert len(snapshot_calls) == 0


@pytest.mark.asyncio
async def test_inventory_job_added_when_enabled():
    """inventory.enabled=True, interval_minutes=60 → job with IntervalTrigger(minutes=60)."""
    providers = {
        "openai": _make_provider(
            inventory_enabled=True,
            inventory_interval_minutes=60,
            inventory_statuses=[Status.VALID],
        )
    }
    scheduler = await _run_worker_capture_scheduler(providers)

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
async def test_no_inventory_job_when_disabled():
    """inventory.enabled=False → no inventory job added."""
    providers = {"openai": _make_provider(inventory_enabled=False)}
    scheduler = await _run_worker_capture_scheduler(providers)

    export_calls = _export_add_job_calls(scheduler)
    inventory_calls = [
        c for c in export_calls if c.kwargs.get("id", "").startswith("inventory_")
    ]
    assert len(inventory_calls) == 0


@pytest.mark.asyncio
async def test_both_jobs_added_when_both_enabled():
    """Both snapshot and inventory enabled → two export jobs added."""
    providers = {
        "openai": _make_provider(
            snapshot_interval_hours=24,
            inventory_enabled=True,
            inventory_interval_minutes=60,
            inventory_statuses=[Status.VALID],
        )
    }
    scheduler = await _run_worker_capture_scheduler(providers)

    export_calls = _export_add_job_calls(scheduler)
    assert len(export_calls) == 2

    ids = [c.kwargs["id"] for c in export_calls]
    assert "snapshot_openai" in ids
    assert "inventory_openai" in ids


@pytest.mark.asyncio
async def test_export_jobs_not_added_for_disabled_provider():
    """provider.enabled=False → no export jobs added for that provider."""
    providers = {
        "disabled_provider": _make_provider(
            enabled=False,
            snapshot_interval_hours=24,
            inventory_enabled=True,
            inventory_statuses=[Status.VALID],
        )
    }
    scheduler = await _run_worker_capture_scheduler(providers)

    export_calls = _export_add_job_calls(scheduler)
    assert len(export_calls) == 0


@pytest.mark.asyncio
async def test_snapshot_job_id_includes_provider_name():
    """Snapshot job_id format includes provider name for uniqueness."""
    providers = {"my_special_provider": _make_provider(snapshot_interval_hours=12)}
    scheduler = await _run_worker_capture_scheduler(providers)

    export_calls = _export_add_job_calls(scheduler)
    assert len(export_calls) == 1
    assert export_calls[0].kwargs["id"] == "snapshot_my_special_provider"


@pytest.mark.asyncio
async def test_inventory_job_id_includes_provider_name():
    """Inventory job_id format includes provider name for uniqueness."""
    providers = {
        "my_special_provider": _make_provider(
            inventory_enabled=True,
            inventory_interval_minutes=30,
            inventory_statuses=[Status.VALID, Status.NO_QUOTA],
        )
    }
    scheduler = await _run_worker_capture_scheduler(providers)

    export_calls = _export_add_job_calls(scheduler)
    inventory_calls = [
        c for c in export_calls if c.kwargs.get("id", "").startswith("inventory_")
    ]
    assert len(inventory_calls) == 1
    assert inventory_calls[0].kwargs["id"] == "inventory_my_special_provider"
