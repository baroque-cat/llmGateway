"""Shared fixtures for keeper-related unit tests.

Provides `mock_run_keeper_dependencies` — a fixture that patches the 13
dependencies shared across test_keeper.py, test_keeper_export_jobs.py,
and test_keeper_metrics.py, and yields a SimpleNamespace with the mock
objects so tests can customize them before calling run_keeper().
"""

from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture
def mock_run_keeper_dependencies():
    """Common mock objects and patches for run_keeper() tests.

    Patches 13 dependencies shared across all keeper test files:
      AsyncIOScheduler, load_config, ConfigAccessor, setup_logging,
      _setup_directories, database.init_db_pool, database.close_db_pool,
      DatabaseManager, HttpClientFactory, run_sync_cycle,
      get_all_probes, get_all_syncers, KeyInventoryExporter.

    Yields a SimpleNamespace with mock objects that tests can customize:
      accessor, scheduler, db_manager, hcf, key_inventory_exporter.

    Tests add file-specific patches (e.g., asyncio.sleep, get_collector)
    on top of these common patches inside their own test functions.

    Note: asyncio.sleep is NOT patched here — each file handles it
    differently (KeyboardInterrupt vs. scheduler.start.side_effect).
    """
    # --- Common mock objects ---
    mock_accessor = MagicMock()
    mock_accessor.get_all_providers.return_value = {}
    mock_accessor.get_enabled_providers.return_value = {}
    mock_accessor.get_database_dsn.return_value = (
        "postgresql://test:test@localhost:5432/testdb"
    )
    mock_accessor.get_pool_config.return_value = MagicMock(min_size=1, max_size=5)
    mock_db_config = MagicMock()
    mock_db_config.vacuum_policy.interval_minutes = 60
    mock_accessor.get_database_config.return_value = mock_db_config

    mock_scheduler = MagicMock()
    mock_scheduler.start = MagicMock()
    mock_scheduler.running = True
    mock_scheduler.shutdown = MagicMock()
    mock_scheduler.print_jobs = MagicMock()

    mock_db_manager = MagicMock()
    mock_db_manager.initialize_schema = AsyncMock()
    mock_db_manager.providers = MagicMock()
    mock_db_manager.providers.sync = AsyncMock()

    mock_hcf = MagicMock()
    mock_hcf.return_value.close_all = AsyncMock()

    # --- Apply common patches ---
    with ExitStack() as stack:
        mock_kie = stack.enter_context(
            patch("src.services.keeper.KeyInventoryExporter")
        )

        stack.enter_context(
            patch(
                "src.services.keeper.AsyncIOScheduler",
                return_value=mock_scheduler,
            )
        )
        stack.enter_context(
            patch("src.services.keeper.load_config", return_value=MagicMock())
        )
        stack.enter_context(
            patch(
                "src.services.keeper.ConfigAccessor",
                return_value=mock_accessor,
            )
        )
        stack.enter_context(patch("src.services.keeper.setup_logging"))
        stack.enter_context(patch("src.services.keeper._setup_directories"))
        stack.enter_context(
            patch(
                "src.services.keeper.database.init_db_pool",
                new_callable=AsyncMock,
            )
        )
        stack.enter_context(
            patch(
                "src.services.keeper.database.close_db_pool",
                new_callable=AsyncMock,
            )
        )
        stack.enter_context(
            patch(
                "src.services.keeper.DatabaseManager",
                return_value=mock_db_manager,
            )
        )
        stack.enter_context(
            patch("src.services.keeper.HttpClientFactory", mock_hcf)
        )
        stack.enter_context(
            patch(
                "src.services.keeper.run_sync_cycle", new_callable=AsyncMock
            )
        )
        stack.enter_context(
            patch("src.services.keeper.get_all_probes", return_value=[])
        )
        stack.enter_context(
            patch("src.services.keeper.get_all_syncers", return_value=[])
        )

        deps = SimpleNamespace(
            accessor=mock_accessor,
            scheduler=mock_scheduler,
            db_manager=mock_db_manager,
            hcf=mock_hcf,
            key_inventory_exporter=mock_kie,
        )

        yield deps