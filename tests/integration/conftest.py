"""Shared helpers for integration tests."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import Request

from src.config.schemas import (
    GatewayPolicyConfig,
    ModelInfo,
    ProviderConfig,
    RetryOnErrorConfig,
    RetryPolicyConfig,
)
from src.core.constants import DebugMode, StreamingMode


def make_mock_request(
    url: str = "http://test/v1/chat/completions", method: str = "POST"
) -> MagicMock:
    """Create a mock FastAPI Request with all necessary state for gateway tests."""
    req = MagicMock(spec=Request)
    req.url.path = "/v1/chat/completions"
    req.url.query = ""
    req.method = method
    req.headers = {"authorization": "Bearer test-token"}
    req.body = AsyncMock(return_value=b'{"model": "gpt-4"}')

    # Create state mock explicitly
    state = MagicMock()
    state.gateway_cache = MagicMock()
    state.gateway_cache.remove_key_from_pool = AsyncMock()

    # HTTP Factory Mock
    http_factory = MagicMock()
    http_factory.get_client_for_provider = AsyncMock(return_value=MagicMock())
    state.http_client_factory = http_factory

    state.db_manager = MagicMock()
    state.db_manager.keys.update_status = AsyncMock()
    state.accessor = MagicMock()
    state.debug_mode_map = {}

    req.app.state = state
    return req


def create_mock_provider_config(
    *,
    provider_type: str = "openai_like",
    models: dict[str, ModelInfo] | None = None,
    streaming_mode: StreamingMode = StreamingMode.AUTO,
    debug_mode: DebugMode = DebugMode.DISABLED,
    retry_enabled: bool = False,
    retry_on_key_error: RetryOnErrorConfig | None = None,
    retry_on_server_error: RetryOnErrorConfig | None = None,
) -> ProviderConfig:
    """Helper to create a ProviderConfig with specified settings."""
    if models is None:
        models = {"gpt-4": ModelInfo()}
    config = ProviderConfig(provider_type=provider_type)
    config.enabled = True
    config.models = models
    config.gateway_policy = GatewayPolicyConfig()
    config.gateway_policy.streaming_mode = streaming_mode.value  # expects string
    config.gateway_policy.debug_mode = debug_mode.value
    # When retry is enabled, at least one sub-config must have attempts >= 1
    on_key_error = retry_on_key_error or (
        RetryOnErrorConfig(attempts=1) if retry_enabled else RetryOnErrorConfig()
    )
    on_server_error = retry_on_server_error or (
        RetryOnErrorConfig(attempts=1) if retry_enabled else RetryOnErrorConfig()
    )
    config.gateway_policy.retry = RetryPolicyConfig(
        enabled=retry_enabled,
        on_key_error=on_key_error,
        on_server_error=on_server_error,
    )
    return config


@pytest.fixture(autouse=True)
def inject_helpers(request):
    """Inject shared helper functions into the test module's namespace."""
    request.module.make_mock_request = make_mock_request
    request.module.create_mock_provider_config = create_mock_provider_config
