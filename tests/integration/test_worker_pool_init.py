#!/usr/bin/env python3

"""
Integration test for worker pool initialization.

Verifies that the worker's run_worker() correctly reads pool configuration
from ConfigAccessor and passes it to database.init_db_pool.

Test ID: IT-S02.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.config.schemas import Config
from src.core.accessor import ConfigAccessor
from src.services.background_worker import run_worker

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_config_with_pool(min_size: int, max_size: int) -> Config:
    """Create a Config with custom pool settings and a valid DSN password."""
    return Config.model_validate(
        {
            "database": {
                "password": "testpass",
                "pool": {"min_size": min_size, "max_size": max_size},
            },
        }
    )


# ---------------------------------------------------------------------------
# IT-S02: Worker passes default pool config to init_db_pool
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_worker_pool_init_default_params():
    """IT-S02: ConfigAccessor with pool.min_size=1, pool.max_size=15 →
    init_db_pool called with min_size=1, max_size=15 during worker startup."""

    cfg = _make_config_with_pool(min_size=1, max_size=15)
    accessor = ConfigAccessor(cfg)
    expected_dsn = accessor.get_database_dsn()

    with (
        patch(
            "src.services.background_worker.load_config",
            return_value=cfg,
        ),
        patch("src.services.background_worker.setup_logging"),
        patch("src.services.background_worker._setup_directories"),
        patch(
            "src.services.background_worker.database.init_db_pool",
            new_callable=AsyncMock,
        ) as mock_init_pool,
        patch(
            "src.services.background_worker.database.close_db_pool",
            new_callable=AsyncMock,
        ),
        patch("src.services.background_worker.DatabaseManager") as mock_dm_cls,
        patch("src.services.background_worker.HttpClientFactory") as mock_hcf_cls,
        patch(
            "src.services.background_worker.get_all_probes",
            return_value=[],
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
            "src.services.background_worker.AsyncIOScheduler",
        ) as mock_scheduler_cls,
        # Make asyncio.sleep raise KeyboardInterrupt to break the infinite loop
        patch(
            "asyncio.sleep",
            new_callable=AsyncMock,
            side_effect=KeyboardInterrupt,
        ),
    ):
        # Configure DatabaseManager mock
        mock_dm_instance = MagicMock()
        mock_dm_instance.initialize_schema = AsyncMock()
        mock_dm_instance.providers = MagicMock()
        mock_dm_instance.providers.sync = AsyncMock()
        mock_dm_cls.return_value = mock_dm_instance

        # Configure HttpClientFactory mock
        mock_hcf_instance = MagicMock()
        mock_hcf_instance.close_all = AsyncMock()
        mock_hcf_cls.return_value = mock_hcf_instance

        # Configure AsyncIOScheduler mock
        mock_scheduler_instance = MagicMock()
        mock_scheduler_instance.start = MagicMock()
        mock_scheduler_instance.running = False
        mock_scheduler_instance.shutdown = MagicMock()
        mock_scheduler_instance.add_job = MagicMock()
        mock_scheduler_instance.print_jobs = MagicMock()
        mock_scheduler_cls.return_value = mock_scheduler_instance

        # run_worker will catch KeyboardInterrupt and shut down gracefully
        await run_worker()

        # Verify init_db_pool was called with the correct pool parameters
        mock_init_pool.assert_called_once_with(expected_dsn, min_size=1, max_size=15)
