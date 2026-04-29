#!/usr/bin/env python3

"""
Integration test for APScheduler + KeyInventoryExporter end-to-end.

Verifies that the background worker correctly registers export jobs with
the scheduler, that disabled exports produce no jobs, and that executing
the export jobs creates NDJSON files on disk.

Test Group: 11 (Integration — APScheduler + Export end-to-end)
"""

import json
from contextlib import asynccontextmanager
from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from apscheduler.triggers.interval import IntervalTrigger

from src.config.schemas import Config
from src.services.background_worker import run_worker
from src.services.inventory_exporter import KeyInventoryExporter

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_config_with_export_enabled() -> Config:
    """Create a Config with a provider that has both snapshot and inventory export enabled."""
    return Config.model_validate(
        {
            "database": {
                "password": "testpass",
                "pool": {"min_size": 1, "max_size": 5},
            },
            "providers": {
                "test-provider": {
                    "provider_type": "gemini",
                    "enabled": True,
                    "key_export": {
                        "enabled": True,
                        "snapshot_interval_hours": 24,
                        "inventory": {
                            "enabled": True,
                            "interval_minutes": 60,
                            "statuses": ["valid", "no_quota"],
                        },
                    },
                },
            },
        }
    )


def _make_config_with_export_disabled() -> Config:
    """Create a Config with a provider where key_export is disabled.

    With ``KeyExportConfig(enabled=False)`` and default sub-settings
    (snapshot_interval_hours=0, inventory.enabled=False), no export
    jobs should be registered by the worker.
    """
    return Config.model_validate(
        {
            "database": {
                "password": "testpass",
                "pool": {"min_size": 1, "max_size": 5},
            },
            "providers": {
                "test-provider": {
                    "provider_type": "gemini",
                    "enabled": True,
                    "key_export": {
                        "enabled": False,
                    },
                },
            },
        }
    )


@asynccontextmanager
async def _mock_pool_acquire(conn: AsyncMock):
    """Async context manager that yields a mock database connection.

    Used as the ``side_effect`` for ``mock_pool.acquire()`` so that each
    call returns a fresh, single-use async context manager — matching the
    behaviour of ``asyncpg.Pool.acquire()``.
    """
    yield conn


# ---------------------------------------------------------------------------
# Test 11.1: Scheduler registers both snapshot and inventory jobs
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scheduler_registers_snapshot_and_inventory_jobs():
    """When ``run_worker()`` is called with both snapshot and inventory export
    enabled, the scheduler should contain both jobs with correct intervals."""

    cfg = _make_config_with_export_enabled()

    with (
        patch("src.services.background_worker.load_config", return_value=cfg),
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
        patch("src.services.background_worker.DatabaseManager") as mock_dm_cls,
        patch("src.services.background_worker.HttpClientFactory") as mock_hcf_cls,
        patch("src.services.background_worker.get_all_probes", return_value=[]),
        patch("src.services.background_worker.get_all_syncers", return_value=[]),
        patch(
            "src.services.background_worker.run_sync_cycle",
            new_callable=AsyncMock,
        ),
        patch(
            "src.services.background_worker.AsyncIOScheduler",
        ) as mock_scheduler_cls,
        patch(
            "asyncio.sleep",
            new_callable=AsyncMock,
            side_effect=KeyboardInterrupt,
        ),
    ):
        # -- DatabaseManager mock --
        mock_dm_instance = MagicMock()
        mock_dm_instance.initialize_schema = AsyncMock()
        mock_dm_instance.providers = MagicMock()
        mock_dm_instance.providers.sync = AsyncMock()
        mock_dm_cls.return_value = mock_dm_instance

        # -- HttpClientFactory mock --
        mock_hcf_instance = MagicMock()
        mock_hcf_instance.close_all = AsyncMock()
        mock_hcf_cls.return_value = mock_hcf_instance

        # -- AsyncIOScheduler mock --
        mock_scheduler_instance = MagicMock()
        mock_scheduler_instance.start = MagicMock()
        mock_scheduler_instance.running = False
        mock_scheduler_instance.shutdown = MagicMock()
        mock_scheduler_instance.add_job = MagicMock()
        mock_scheduler_instance.print_jobs = MagicMock()
        mock_scheduler_cls.return_value = mock_scheduler_instance

        # Run the worker (KeyboardInterrupt breaks the infinite loop)
        await run_worker()

        # Inspect all add_job calls recorded on the mock scheduler
        add_job_calls = mock_scheduler_instance.add_job.call_args_list
        job_ids = [call.kwargs.get("id", "") for call in add_job_calls]

        # --- Snapshot job must be present ---
        assert (
            "snapshot_test-provider" in job_ids
        ), f"Expected 'snapshot_test-provider' in job IDs, got: {job_ids}"

        snapshot_call = next(
            c for c in add_job_calls if c.kwargs.get("id") == "snapshot_test-provider"
        )
        snapshot_trigger = snapshot_call.kwargs["trigger"]
        assert isinstance(snapshot_trigger, IntervalTrigger)
        assert snapshot_trigger.interval == timedelta(
            hours=24
        ), f"Snapshot interval should be 24h, got {snapshot_trigger.interval}"

        # --- Inventory job must be present ---
        assert (
            "inventory_test-provider" in job_ids
        ), f"Expected 'inventory_test-provider' in job IDs, got: {job_ids}"

        inventory_call = next(
            c for c in add_job_calls if c.kwargs.get("id") == "inventory_test-provider"
        )
        inventory_trigger = inventory_call.kwargs["trigger"]
        assert isinstance(inventory_trigger, IntervalTrigger)
        assert inventory_trigger.interval == timedelta(
            minutes=60
        ), f"Inventory interval should be 60min, got {inventory_trigger.interval}"


# ---------------------------------------------------------------------------
# Test 11.2: No export jobs when export is disabled
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scheduler_no_jobs_when_export_disabled():
    """When ``KeyExportConfig(enabled=False)`` is set (with default sub-settings),
    the scheduler should have no export-related jobs."""

    cfg = _make_config_with_export_disabled()

    with (
        patch("src.services.background_worker.load_config", return_value=cfg),
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
        patch("src.services.background_worker.DatabaseManager") as mock_dm_cls,
        patch("src.services.background_worker.HttpClientFactory") as mock_hcf_cls,
        patch("src.services.background_worker.get_all_probes", return_value=[]),
        patch("src.services.background_worker.get_all_syncers", return_value=[]),
        patch(
            "src.services.background_worker.run_sync_cycle",
            new_callable=AsyncMock,
        ),
        patch(
            "src.services.background_worker.AsyncIOScheduler",
        ) as mock_scheduler_cls,
        patch(
            "asyncio.sleep",
            new_callable=AsyncMock,
            side_effect=KeyboardInterrupt,
        ),
    ):
        # -- DatabaseManager mock --
        mock_dm_instance = MagicMock()
        mock_dm_instance.initialize_schema = AsyncMock()
        mock_dm_instance.providers = MagicMock()
        mock_dm_instance.providers.sync = AsyncMock()
        mock_dm_cls.return_value = mock_dm_instance

        # -- HttpClientFactory mock --
        mock_hcf_instance = MagicMock()
        mock_hcf_instance.close_all = AsyncMock()
        mock_hcf_cls.return_value = mock_hcf_instance

        # -- AsyncIOScheduler mock --
        mock_scheduler_instance = MagicMock()
        mock_scheduler_instance.start = MagicMock()
        mock_scheduler_instance.running = False
        mock_scheduler_instance.shutdown = MagicMock()
        mock_scheduler_instance.add_job = MagicMock()
        mock_scheduler_instance.print_jobs = MagicMock()
        mock_scheduler_cls.return_value = mock_scheduler_instance

        await run_worker()

        add_job_calls = mock_scheduler_instance.add_job.call_args_list

        # Collect only export-related job IDs (snapshot_* or inventory_*)
        export_job_ids = [
            call.kwargs.get("id", "")
            for call in add_job_calls
            if call.kwargs.get("id", "").startswith("snapshot_")
            or call.kwargs.get("id", "").startswith("inventory_")
        ]

        assert (
            export_job_ids == []
        ), f"Expected no export jobs when key_export is disabled, but found: {export_job_ids}"


# ---------------------------------------------------------------------------
# Test 11.3: Job execution creates NDJSON files on disk
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scheduler_job_execution_creates_files(tmp_path):
    """When the export job is executed (simulating immediate APScheduler
    execution), NDJSON files are created on disk with correct content."""

    exporter = KeyInventoryExporter()
    mock_conn = AsyncMock()
    mock_db_manager = MagicMock()
    provider_name = "test-provider"

    # --- Snapshot rows (returned by the mock DB query) ---
    snapshot_rows = [
        {
            "key_id": 1,
            "key_value": "sk-abcdefghij1234567890",
            "model_name": "gemini-pro",
            "status": "valid",
            "next_check_time": None,
        },
        {
            "key_id": 2,
            "key_value": "sk-xyzabcdefghij45678",
            "model_name": "gemini-pro-vision",
            "status": "no_quota",
            "next_check_time": None,
        },
    ]
    mock_conn.fetch = AsyncMock(return_value=snapshot_rows)

    # Mock pool whose acquire() yields mock_conn via async context manager
    mock_pool = MagicMock()
    mock_pool.acquire = MagicMock(
        side_effect=lambda: _mock_pool_acquire(mock_conn),
    )

    with (
        patch("src.services.inventory_exporter.get_pool", return_value=mock_pool),
        patch("src.services.inventory_exporter._EXPORT_ROOT", str(tmp_path)),
    ):
        # ---- Simulate immediate scheduler execution of snapshot job ----
        await exporter.export_snapshot(provider_name, mock_db_manager)

        snapshot_path = tmp_path / provider_name / "all_keys.ndjson"
        assert snapshot_path.exists(), f"Snapshot file not found at {snapshot_path}"

        snapshot_content = snapshot_path.read_text(encoding="utf-8")
        snapshot_lines = [line for line in snapshot_content.strip().split("\n") if line]
        assert (
            len(snapshot_lines) == 2
        ), f"Expected 2 snapshot records, got {len(snapshot_lines)}"

        first_record = json.loads(snapshot_lines[0])
        assert first_record["key_id"] == 1
        assert first_record["key_prefix"] == "sk-abcdefg"
        assert first_record["model_name"] == "gemini-pro"
        assert first_record["status"] == "valid"
        assert "next_check_time" in first_record

        # ---- Simulate immediate scheduler execution of inventory job ----
        inventory_rows = [
            {
                "key_id": 1,
                "key_value": "sk-abcdefghij1234567890",
                "model_name": "gemini-pro",
                "next_check_time": None,
            },
        ]
        mock_conn.fetch = AsyncMock(return_value=inventory_rows)

        await exporter.export_inventory(provider_name, mock_db_manager, ["valid"])

        inventory_path = tmp_path / provider_name / "valid" / "keys.ndjson"
        assert inventory_path.exists(), f"Inventory file not found at {inventory_path}"

        inventory_content = inventory_path.read_text(encoding="utf-8")
        inventory_lines = [
            line for line in inventory_content.strip().split("\n") if line
        ]
        assert (
            len(inventory_lines) == 1
        ), f"Expected 1 inventory record, got {len(inventory_lines)}"

        inv_record = json.loads(inventory_lines[0])
        assert inv_record["key_id"] == 1
        assert inv_record["status"] == "valid"
        assert inv_record["model_name"] == "gemini-pro"
