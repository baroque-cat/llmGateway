#!/usr/bin/env python3

"""
Integration tests for Anthropic provider factory registration and configuration loading.

This module tests that:
1. The Anthropic provider is properly registered in the provider factory
2. Unknown provider types raise appropriate errors
3. YAML configuration with 'anthropic' provider_type is correctly parsed
"""

from unittest.mock import mock_open, patch

import pytest
from pydantic import ValidationError

from src.config.loader import ConfigLoader
from src.config.schemas import ModelInfo, ProviderConfig
from src.providers import _PROVIDER_CLASSES, get_provider
from src.providers.impl.anthropic import AnthropicProvider


class TestAnthropicProviderFactory:
    """Test suite for Anthropic provider factory registration."""

    def test_anthropic_registered_in_provider_classes(self):
        """Verify that _PROVIDER_CLASSES contains 'anthropic' mapping to AnthropicProvider."""
        assert "anthropic" in _PROVIDER_CLASSES
        assert _PROVIDER_CLASSES["anthropic"] is AnthropicProvider

    def test_get_provider_creates_anthropic_instance(self):
        """Verify that get_provider with anthropic type creates an AnthropicProvider instance."""
        config = ProviderConfig(
            provider_type="anthropic",
            api_base_url="https://api.anthropic.com",
            models={"claude-3-opus": ModelInfo()},
        )
        provider = get_provider("test_anthropic", config)
        assert isinstance(provider, AnthropicProvider)
        assert provider.name == "test_anthropic"
        assert provider.config is config

    def test_get_provider_unknown_type_raises_validationerror(self):
        """Verify that ProviderConfig with non-existent provider type raises ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            ProviderConfig(provider_type="nonexistent")
        # Should mention the valid enum values
        error_msg = str(exc_info.value)
        assert "nonexistent" in error_msg or "provider_type" in error_msg


class TestAnthropicConfigurationLoading:
    """Test suite for loading YAML configuration with anthropic provider_type."""

    def test_config_loader_with_anthropic_provider(self):
        """Test that YAML configuration with 'anthropic' section is correctly parsed."""
        mock_yaml_content = """database:
  host: localhost
  port: 5432
  password: test_password
keeper:
  max_concurrent_providers: 5
providers:
  anthropic_main:
    provider_type: anthropic
    enabled: true
    api_base_url: https://api.anthropic.com
    default_model: claude-3-opus
    models:
      claude-3-opus:
        endpoint_suffix: /v1/messages
        test_payload:
          max_tokens: 10
          messages: []
      claude-3-sonnet:
        endpoint_suffix: /v1/messages
        test_payload:
          max_tokens: 10
          messages: []
    timeouts:
      connect: 10.0
      read: 30.0
      write: 30.0
      pool: 30.0
    access_control:
      gateway_access_token: anthropic_token
    gateway_policy:
      debug_mode: disabled
      streaming_mode: auto
"""
        with (
            patch("os.path.exists", return_value=True),
            patch("builtins.open", mock_open(read_data=mock_yaml_content)),
        ):
            loader = ConfigLoader(path="dummy_path.yaml")
            config = loader.load()

            # Verify provider exists
            assert "anthropic_main" in config.providers
            provider_config = config.providers["anthropic_main"]

            # Verify basic fields
            assert provider_config.provider_type == "anthropic"
            assert provider_config.enabled is True
            assert provider_config.api_base_url == "https://api.anthropic.com"
            assert provider_config.default_model == "claude-3-opus"

            # Verify models
            assert "claude-3-opus" in provider_config.models
            assert "claude-3-sonnet" in provider_config.models
            model_info = provider_config.models["claude-3-opus"]
            assert model_info.endpoint_suffix == "/v1/messages"
            assert model_info.test_payload == {"max_tokens": 10, "messages": []}

            # Verify nested configs
            assert provider_config.timeouts.connect == 10.0
            assert provider_config.timeouts.read == 30.0
            assert provider_config.timeouts.write == 30.0
            assert provider_config.timeouts.pool == 30.0
            assert (
                provider_config.access_control.gateway_access_token == "anthropic_token"
            )
            assert provider_config.gateway_policy.debug_mode == "disabled"
            assert provider_config.gateway_policy.streaming_mode == "auto"

    def test_provider_instance_from_loaded_config(self):
        """Test that a provider instance can be created from the loaded configuration."""
        mock_yaml_content = """providers:
  anthropic_test:
    provider_type: anthropic
    api_base_url: https://api.anthropic.com
    models:
      claude-3-opus: {}
"""
        with (
            patch("os.path.exists", return_value=True),
            patch("builtins.open", mock_open(read_data=mock_yaml_content)),
        ):
            loader = ConfigLoader(path="dummy.yaml")
            config = loader.load()
            provider_config = config.providers["anthropic_test"]

            # Create provider instance
            provider = get_provider("anthropic_test", provider_config)
            assert isinstance(provider, AnthropicProvider)
            assert provider.name == "anthropic_test"
            assert provider.config.api_base_url == "https://api.anthropic.com"
            # Models dict contains ModelInfo instances
            assert "claude-3-opus" in provider.config.models
            model_info = provider.config.models["claude-3-opus"]
            assert model_info.endpoint_suffix == ""
            assert model_info.test_payload == {}
