#!/usr/bin/env python3

"""
Tests for the provider factory function (get_provider).

This module tests the factory function in src/providers/__init__.py,
ensuring that it correctly creates provider instances based on configuration
and raises appropriate errors for invalid inputs.
"""

from unittest.mock import MagicMock

import pytest

from src.config.schemas import ProviderConfig
from src.core.constants import ProviderType
from src.providers import get_provider
from src.providers.impl.gemini import GeminiProvider
from src.providers.impl.openai_like import OpenAILikeProvider


class TestProviderFactory:
    """Test suite for the get_provider factory function."""

    def test_get_provider_creates_openai_like(self):
        """Test get_provider creates OpenAILikeProvider when provider_type is OPENAI_LIKE."""
        config = ProviderConfig(provider_type=ProviderType.OPENAI_LIKE)

        provider = get_provider("test_openai", config)

        assert isinstance(provider, OpenAILikeProvider)
        assert provider.name == "test_openai"

    def test_get_provider_creates_gemini(self):
        """Test get_provider creates GeminiProvider when provider_type is GEMINI."""
        config = ProviderConfig(provider_type=ProviderType.GEMINI)

        provider = get_provider("test_gemini", config)

        assert isinstance(provider, GeminiProvider)
        assert provider.name == "test_gemini"

    def test_get_provider_unknown_type_raises(self):
        """Test get_provider raises ValueError for an unknown provider_type."""
        mock_config = MagicMock(spec=ProviderConfig)
        mock_config.provider_type = "nonexistent_provider"

        with pytest.raises(ValueError, match="Unknown provider type"):
            get_provider("test_unknown", mock_config)

    def test_get_provider_empty_provider_type_raises(self):
        """Test get_provider raises ValueError when provider_type is empty."""
        mock_config = MagicMock(spec=ProviderConfig)
        mock_config.provider_type = ""

        with pytest.raises(ValueError, match="Provider type is not specified"):
            get_provider("test_empty", mock_config)
