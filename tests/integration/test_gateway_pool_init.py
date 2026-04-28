#!/usr/bin/env python3

"""
Integration test for gateway pool initialization.

Verifies that the gateway's lifespan correctly reads pool configuration
from ConfigAccessor and passes it to database.init_db_pool.

Test ID: IT-S01.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from src.config.schemas import Config
from src.core.accessor import ConfigAccessor
from src.services.gateway_service import create_app

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_accessor_with_pool(min_size: int, max_size: int) -> ConfigAccessor:
    """Create a ConfigAccessor with custom pool settings and a valid DSN."""
    cfg = Config.model_validate(
        {
            "database": {
                "password": "testpass",
                "pool": {"min_size": min_size, "max_size": max_size},
            },
        }
    )
    return ConfigAccessor(cfg)


# ---------------------------------------------------------------------------
# IT-S01: Gateway lifespan passes pool config to init_db_pool
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_gateway_pool_init_custom_params():
    """IT-S01: ConfigAccessor with pool.min_size=2, pool.max_size=10 →
    init_db_pool called with min_size=2, max_size=10 during gateway lifespan."""

    accessor = _make_accessor_with_pool(min_size=2, max_size=10)
    expected_dsn = accessor.get_database_dsn()

    with (
        patch(
            "src.services.gateway_service.database.init_db_pool",
            new_callable=AsyncMock,
        ) as mock_init_pool,
        patch(
            "src.services.gateway_service.database.close_db_pool",
            new_callable=AsyncMock,
        ),
        patch("src.services.gateway_service.DatabaseManager") as mock_dm_cls,
        patch("src.services.gateway_service.GatewayCache") as mock_gc_cls,
        patch("src.services.gateway_service.HttpClientFactory") as mock_hcf_cls,
        patch(
            "src.services.gateway_service._cache_refresh_loop",
            new_callable=AsyncMock,
        ) as mock_refresh_loop,
        patch(
            "src.services.gateway_service.MetricsService",
        ) as mock_metrics_cls,
    ):
        # Configure DatabaseManager mock
        mock_dm_instance = MagicMock()
        mock_dm_instance.wait_for_schema_ready = AsyncMock()
        mock_dm_instance.keys = MagicMock()
        mock_dm_cls.return_value = mock_dm_instance

        # Configure GatewayCache mock
        mock_gc_instance = MagicMock()
        mock_gc_instance.populate_caches = AsyncMock()
        mock_gc_cls.return_value = mock_gc_instance

        # Configure HttpClientFactory mock
        mock_hcf_instance = MagicMock()
        mock_hcf_instance.close_all = AsyncMock()
        mock_hcf_cls.return_value = mock_hcf_instance

        # Configure MetricsService mock
        mock_metrics_instance = MagicMock()
        mock_metrics_instance.start = AsyncMock()
        mock_metrics_instance.stop = AsyncMock()
        mock_metrics_cls.return_value = mock_metrics_instance

        # Create the app and trigger lifespan via TestClient
        app = create_app(accessor)

        with TestClient(app):
            pass  # lifespan startup + shutdown triggered

        # Verify init_db_pool was called with the correct pool parameters
        mock_init_pool.assert_called_once_with(expected_dsn, min_size=2, max_size=10)
