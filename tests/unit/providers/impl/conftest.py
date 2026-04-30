"""Shared fixtures for Anthropic provider tests."""

from unittest.mock import MagicMock

import pytest

from src.config.schemas import (
    ErrorParsingConfig,
    GatewayPolicyConfig,
    ProviderConfig,
)
from src.providers.impl.anthropic import AnthropicProvider


@pytest.fixture
def create_mock_anthropic_provider():
    """
    Factory fixture for creating mock AnthropicProvider instances.

    Returns a callable that accepts the following parameters:
    - name: Provider instance name (default: "test_provider")
    - error_config: ErrorParsingConfig instance (default: disabled)
    - worker_health_policy: Mock health policy (default: MagicMock())
    - gateway_policy: Mock gateway policy (default: MagicMock(spec=GatewayPolicyConfig))
    - models: Dict of model names to mock objects (default: 3 standard Anthropic models)
    - api_base_url: API base URL (default: "https://api.anthropic.com")
    - timeouts_pool: Pool timeout value (default: 5.0)
    """

    def _factory(
        name: str = "test_provider",
        error_config: ErrorParsingConfig | None = None,
        worker_health_policy: MagicMock | None = None,
        gateway_policy: MagicMock | None = None,
        models: dict | None = None,
        api_base_url: str = "https://api.anthropic.com",
        timeouts_pool: float = 5.0,
    ):
        if error_config is None:
            error_config = ErrorParsingConfig(enabled=False, rules=[])
        if gateway_policy is None:
            gateway_policy = MagicMock(spec=GatewayPolicyConfig)
        if worker_health_policy is None:
            worker_health_policy = MagicMock()
        if models is None:
            models = {
                "claude-3-opus-20240229": MagicMock(),
                "claude-3-sonnet-20240229": MagicMock(),
                "claude-3-haiku-20240307": MagicMock(),
            }

        mock_config = MagicMock(spec=ProviderConfig)
        mock_config.gateway_policy = gateway_policy
        mock_config.error_parsing = error_config
        mock_config.worker_health_policy = worker_health_policy
        mock_config.provider_type = "anthropic"
        mock_config.api_base_url = api_base_url
        mock_config.default_model = "claude-3-opus-20240229"
        mock_config.models = models
        mock_config.access_control = MagicMock()
        mock_config.access_control.gateway_access_token = "test_token"
        mock_config.health_policy = MagicMock()
        mock_config.proxy_config = MagicMock()
        mock_config.proxy_config.mode = "none"
        mock_config.timeouts = MagicMock()
        mock_config.timeouts.total = 30.0
        mock_config.timeouts.connect = 10.0
        mock_config.timeouts.read = 30.0
        mock_config.timeouts.write = 30.0
        mock_config.timeouts.pool = timeouts_pool

        return AnthropicProvider(name, mock_config)

    return _factory
