"""Integration tests for NetworkGuard 503 behavior in gateway endpoints.

Verifies that:
- /readyz returns 503 with Retry-After: 60 when guard is DOWN and enforcing
- /healthz returns 200 regardless of guard state
- Proxy requests return 503 when guard is DOWN
- Provider is not called when guard is DOWN
- Log mode allows requests even when guard is DOWN
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from src.config.schemas import NetworkGuardConfig
from src.core.network_guard import set_network_guard
from tests._canonical import CanonicalConfig
from tests.integration._helpers import create_mock_provider_config


@pytest.fixture
def guard_config_pause(tmp_path):
    """Create a NetworkGuardConfig in pause mode with failing probe."""
    return NetworkGuardConfig(
        enabled=True,
        mode="pause",
        probe_urls=["http://127.0.0.1:1"],  # Port 1 should refuse quickly
        probe_interval_sec=30,
        probe_connect_timeout_sec=0.1,
        probe_total_timeout_sec=0.2,
        min_probe_successes=1,
        fail_threshold=1,
        passive_window_sec=60,
        passive_min_providers=3,
        passive_min_failures=6,
        startup_probe=True,
        auto_recover=False,
        marker_path=str(tmp_path / "state.json"),
    )


@pytest.fixture
def guard_config_log(tmp_path):
    """Create a NetworkGuardConfig in log mode with failing probe."""
    return NetworkGuardConfig(
        enabled=True,
        mode="log",  # Log mode, not pause
        probe_urls=["http://127.0.0.1:1"],  # Port 1 should refuse quickly
        probe_interval_sec=30,
        probe_connect_timeout_sec=0.1,
        probe_total_timeout_sec=0.2,
        min_probe_successes=1,
        fail_threshold=1,
        passive_window_sec=60,
        passive_min_providers=3,
        passive_min_failures=6,
        startup_probe=True,
        auto_recover=False,
        marker_path=str(tmp_path / "state.json"),
    )


def test_readyz_returns_503_when_guard_down_pause_mode(guard_config_pause):
    """/readyz returns 503 with Retry-After: 60 when guard is DOWN in pause mode."""
    from src.services.gateway.gateway_service import create_app

    accessor = MagicMock()
    provider_config = create_mock_provider_config()
    accessor.get_enabled_providers.return_value = {"test_instance": provider_config}
    accessor.get_provider_or_raise.return_value = provider_config
    accessor.get_database_dsn.return_value = "postgresql://user:pass@localhost/test"
    accessor.get_network_guard_config.return_value = guard_config_pause

    with (
        patch(
            "src.services.gateway.gateway_service.database.init_db_pool",
            new_callable=AsyncMock,
        ),
        patch(
            "src.services.gateway.gateway_service.database.close_db_pool",
            new_callable=AsyncMock,
        ),
        patch(
            "src.services.gateway.gateway_service.DatabaseManager"
        ) as MockDatabaseManager,
        patch(
            "src.services.gateway.gateway_service.HttpClientFactory"
        ) as MockHttpClientFactory,
        patch("src.services.gateway.gateway_service.GatewayCache") as MockGatewayCache,
        patch(
            "src.services.gateway.gateway_service._get_token_from_headers"
        ) as mock_get_token,
        patch("src.services.gateway.gateway_service.get_provider") as mock_get_provider,
    ):
        mock_db_manager = MagicMock()
        mock_db_manager.wait_for_schema_ready = AsyncMock()
        MockDatabaseManager.return_value = mock_db_manager
        mock_http_factory = MagicMock()
        mock_http_factory.close_all = AsyncMock()
        MockHttpClientFactory.return_value = mock_http_factory
        mock_cache = MagicMock()
        mock_cache.get_instance_name_by_token.return_value = "test_instance"
        mock_cache.get_key_from_pool.return_value = (1, "fake_api_key")
        mock_cache.populate_caches = AsyncMock()
        MockGatewayCache.return_value = mock_cache
        mock_get_token.return_value = "valid_token"
        mock_provider = MagicMock()
        mock_get_provider.return_value = mock_provider

        app = create_app(accessor)

        try:
            with TestClient(app) as client:
                response = client.get("/readyz")
                assert response.status_code == 503
                assert response.headers.get("Retry-After") == "60"
                data = response.json()
                assert data["status"] == "network_down"
                assert "guard" in data
        finally:
            set_network_guard(None)


def test_healthz_returns_200_when_guard_down(guard_config_pause):
    """/healthz returns 200 regardless of guard state."""
    from src.services.gateway.gateway_service import create_app

    accessor = MagicMock()
    provider_config = create_mock_provider_config()
    accessor.get_enabled_providers.return_value = {"test_instance": provider_config}
    accessor.get_provider_or_raise.return_value = provider_config
    accessor.get_database_dsn.return_value = "postgresql://user:pass@localhost/test"
    accessor.get_network_guard_config.return_value = guard_config_pause

    with (
        patch(
            "src.services.gateway.gateway_service.database.init_db_pool",
            new_callable=AsyncMock,
        ),
        patch(
            "src.services.gateway.gateway_service.database.close_db_pool",
            new_callable=AsyncMock,
        ),
        patch(
            "src.services.gateway.gateway_service.DatabaseManager"
        ) as MockDatabaseManager,
        patch(
            "src.services.gateway.gateway_service.HttpClientFactory"
        ) as MockHttpClientFactory,
        patch("src.services.gateway.gateway_service.GatewayCache") as MockGatewayCache,
        patch(
            "src.services.gateway.gateway_service._get_token_from_headers"
        ) as mock_get_token,
        patch("src.services.gateway.gateway_service.get_provider") as mock_get_provider,
    ):
        mock_db_manager = MagicMock()
        mock_db_manager.wait_for_schema_ready = AsyncMock()
        MockDatabaseManager.return_value = mock_db_manager
        mock_http_factory = MagicMock()
        mock_http_factory.close_all = AsyncMock()
        MockHttpClientFactory.return_value = mock_http_factory
        mock_cache = MagicMock()
        mock_cache.get_instance_name_by_token.return_value = "test_instance"
        mock_cache.get_key_from_pool.return_value = (1, "fake_api_key")
        mock_cache.populate_caches = AsyncMock()
        MockGatewayCache.return_value = mock_cache
        mock_get_token.return_value = "valid_token"
        mock_provider = MagicMock()
        mock_get_provider.return_value = mock_provider

        app = create_app(accessor)

        try:
            with TestClient(app) as client:
                response = client.get("/healthz")
                assert response.status_code == 200
                data = response.json()
                assert data["status"] == "ok"
        finally:
            set_network_guard(None)


def test_proxy_request_returns_503_when_guard_down(guard_config_pause):
    """Proxy requests return 503 when guard is DOWN in pause mode."""
    from src.services.gateway.gateway_service import create_app

    accessor = MagicMock()
    provider_config = create_mock_provider_config()
    accessor.get_enabled_providers.return_value = {"test_instance": provider_config}
    accessor.get_provider_or_raise.return_value = provider_config
    accessor.get_database_dsn.return_value = "postgresql://user:pass@localhost/test"
    accessor.get_network_guard_config.return_value = guard_config_pause

    with (
        patch(
            "src.services.gateway.gateway_service.database.init_db_pool",
            new_callable=AsyncMock,
        ),
        patch(
            "src.services.gateway.gateway_service.database.close_db_pool",
            new_callable=AsyncMock,
        ),
        patch(
            "src.services.gateway.gateway_service.DatabaseManager"
        ) as MockDatabaseManager,
        patch(
            "src.services.gateway.gateway_service.HttpClientFactory"
        ) as MockHttpClientFactory,
        patch("src.services.gateway.gateway_service.GatewayCache") as MockGatewayCache,
        patch(
            "src.services.gateway.gateway_service._get_token_from_headers"
        ) as mock_get_token,
        patch("src.services.gateway.gateway_service.get_provider") as mock_get_provider,
    ):
        mock_db_manager = MagicMock()
        mock_db_manager.wait_for_schema_ready = AsyncMock()
        MockDatabaseManager.return_value = mock_db_manager
        mock_http_factory = MagicMock()
        mock_http_factory.close_all = AsyncMock()
        MockHttpClientFactory.return_value = mock_http_factory
        mock_cache = MagicMock()
        mock_cache.get_instance_name_by_token.return_value = "test_instance"
        mock_cache.get_key_from_pool.return_value = (1, "fake_api_key")
        mock_cache.populate_caches = AsyncMock()
        MockGatewayCache.return_value = mock_cache
        mock_get_token.return_value = "valid_token"
        mock_provider = MagicMock()
        mock_get_provider.return_value = mock_provider

        app = create_app(accessor)

        with (
            patch(
                "src.services.gateway.gateway_service._handle_full_stream_request",
                new_callable=AsyncMock,
            ) as mock_handler,
        ):
            mock_handler.return_value = JSONResponse(content={"result": "ok"})

            try:
                with TestClient(app) as client:
                    response = client.post(
                        "/v1/chat/completions",
                        json={
                            "model": CanonicalConfig.from_example_files().canonical_model_names[
                                0
                            ],
                            "messages": [],
                        },
                        headers={"Authorization": "Bearer valid_token"},
                    )
                    assert response.status_code == 503
                    assert response.headers.get("Retry-After") == "60"
                    data = response.json()
                    assert "error" in data
                    assert "Network outage guard is active" in data["error"]

                    # Verify handler was NOT called
                    assert not mock_handler.called
            finally:
                set_network_guard(None)


def test_readyz_returns_200_when_guard_log_mode(guard_config_log):
    """/readyz returns 200 when guard is DOWN but in log mode (not enforcing)."""
    from src.services.gateway.gateway_service import create_app

    accessor = MagicMock()
    provider_config = create_mock_provider_config()
    accessor.get_enabled_providers.return_value = {"test_instance": provider_config}
    accessor.get_provider_or_raise.return_value = provider_config
    accessor.get_database_dsn.return_value = "postgresql://user:pass@localhost/test"
    accessor.get_network_guard_config.return_value = guard_config_log

    with (
        patch(
            "src.services.gateway.gateway_service.database.init_db_pool",
            new_callable=AsyncMock,
        ),
        patch(
            "src.services.gateway.gateway_service.database.close_db_pool",
            new_callable=AsyncMock,
        ),
        patch(
            "src.services.gateway.gateway_service.DatabaseManager"
        ) as MockDatabaseManager,
        patch(
            "src.services.gateway.gateway_service.HttpClientFactory"
        ) as MockHttpClientFactory,
        patch("src.services.gateway.gateway_service.GatewayCache") as MockGatewayCache,
        patch(
            "src.services.gateway.gateway_service._get_token_from_headers"
        ) as mock_get_token,
        patch("src.services.gateway.gateway_service.get_provider") as mock_get_provider,
    ):
        mock_db_manager = MagicMock()
        mock_db_manager.wait_for_schema_ready = AsyncMock()
        MockDatabaseManager.return_value = mock_db_manager
        mock_http_factory = MagicMock()
        mock_http_factory.close_all = AsyncMock()
        MockHttpClientFactory.return_value = mock_http_factory
        mock_cache = MagicMock()
        mock_cache.get_instance_name_by_token.return_value = "test_instance"
        mock_cache.get_key_from_pool.return_value = (1, "fake_api_key")
        mock_cache.populate_caches = AsyncMock()
        MockGatewayCache.return_value = mock_cache
        mock_get_token.return_value = "valid_token"
        mock_provider = MagicMock()
        mock_get_provider.return_value = mock_provider

        app = create_app(accessor)

        try:
            with TestClient(app) as client:
                response = client.get("/readyz")
                assert response.status_code == 200
                data = response.json()
                assert data["status"] == "ready"
        finally:
            set_network_guard(None)


def test_proxy_request_proceeds_when_guard_log_mode(guard_config_log):
    """Proxy requests proceed when guard is DOWN but in log mode."""
    from src.services.gateway.gateway_service import create_app

    accessor = MagicMock()
    provider_config = create_mock_provider_config()
    accessor.get_enabled_providers.return_value = {"test_instance": provider_config}
    accessor.get_provider_or_raise.return_value = provider_config
    accessor.get_database_dsn.return_value = "postgresql://user:pass@localhost/test"
    accessor.get_network_guard_config.return_value = guard_config_log

    with (
        patch(
            "src.services.gateway.gateway_service.database.init_db_pool",
            new_callable=AsyncMock,
        ),
        patch(
            "src.services.gateway.gateway_service.database.close_db_pool",
            new_callable=AsyncMock,
        ),
        patch(
            "src.services.gateway.gateway_service.DatabaseManager"
        ) as MockDatabaseManager,
        patch(
            "src.services.gateway.gateway_service.HttpClientFactory"
        ) as MockHttpClientFactory,
        patch("src.services.gateway.gateway_service.GatewayCache") as MockGatewayCache,
        patch(
            "src.services.gateway.gateway_service._get_token_from_headers"
        ) as mock_get_token,
        patch("src.services.gateway.gateway_service.get_provider") as mock_get_provider,
    ):
        mock_db_manager = MagicMock()
        mock_db_manager.wait_for_schema_ready = AsyncMock()
        MockDatabaseManager.return_value = mock_db_manager
        mock_http_factory = MagicMock()
        mock_http_factory.close_all = AsyncMock()
        MockHttpClientFactory.return_value = mock_http_factory
        mock_cache = MagicMock()
        mock_cache.get_instance_name_by_token.return_value = "test_instance"
        mock_cache.get_key_from_pool.return_value = (1, "fake_api_key")
        mock_cache.populate_caches = AsyncMock()
        MockGatewayCache.return_value = mock_cache
        mock_get_token.return_value = "valid_token"
        mock_provider = MagicMock()
        mock_get_provider.return_value = mock_provider

        app = create_app(accessor)

        with (
            patch(
                "src.services.gateway.gateway_service._handle_full_stream_request",
                new_callable=AsyncMock,
            ) as mock_handler,
        ):
            mock_handler.return_value = JSONResponse(content={"result": "ok"})

            try:
                with TestClient(app) as client:
                    response = client.post(
                        "/v1/chat/completions",
                        json={
                            "model": CanonicalConfig.from_example_files().canonical_model_names[
                                0
                            ],
                            "messages": [],
                        },
                        headers={"Authorization": "Bearer valid_token"},
                    )
                    assert response.status_code == 200

                    # Verify handler WAS called (log mode doesn't block)
                    assert mock_handler.called
            finally:
                set_network_guard(None)
