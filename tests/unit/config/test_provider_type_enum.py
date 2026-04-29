#!/usr/bin/env python3

"""
Test suite for ProviderType enum validation and its integration with ProviderConfig.

These tests verify that:
- ProviderType is a StrEnum with exactly three members (ANTHROPIC, OPENAI_LIKE, GEMINI)
- ProviderConfig accepts valid ProviderType values and rejects invalid/missing ones
- YAML config loading correctly handles valid and invalid provider_type values
- ProviderType enum stays in sync with _PROVIDER_CLASSES registry

Reference: openspec/changes/harden-config-validation/test-plan.md, lines 25-35
"""

from enum import StrEnum
from unittest.mock import mock_open, patch

import pytest
from pydantic import ValidationError

from src.config.loader import ConfigLoader
from src.config.schemas import ProviderConfig
from src.core.constants import ProviderType
from src.providers import _PROVIDER_CLASSES


class TestProviderTypeEnum:
    """Tests for the ProviderType StrEnum definition."""

    def test_provider_type_enum_has_three_members(self):
        """
        Verify ProviderType has exactly three members: ANTHROPIC, OPENAI_LIKE, GEMINI
        with values 'anthropic', 'openai_like', 'gemini'.
        """
        members = list(ProviderType)
        assert len(members) == 3
        assert members == [
            ProviderType.ANTHROPIC,
            ProviderType.OPENAI_LIKE,
            ProviderType.GEMINI,
        ]
        assert ProviderType.ANTHROPIC.value == "anthropic"
        assert ProviderType.OPENAI_LIKE.value == "openai_like"
        assert ProviderType.GEMINI.value == "gemini"

    def test_provider_type_enum_is_str_enum(self):
        """
        Verify ProviderType inherits from StrEnum and that enum members
        are directly comparable to their string values.
        """
        assert issubclass(ProviderType, StrEnum)
        # StrEnum members should be equal to their string values
        assert ProviderType.GEMINI == "gemini"
        assert ProviderType.ANTHROPIC == "anthropic"
        assert ProviderType.OPENAI_LIKE == "openai_like"


class TestProviderConfigProviderTypeValidation:
    """Tests for ProviderConfig's provider_type field validation."""

    def test_provider_config_valid_provider_type_accepted(self):
        """
        Verify that ProviderConfig accepts a valid ProviderType string value
        and coerces it to the corresponding ProviderType enum member.
        """
        provider = ProviderConfig(provider_type="gemini")
        assert provider.provider_type == ProviderType.GEMINI
        assert provider.provider_type == "gemini"  # StrEnum is also a str

    def test_provider_config_invalid_provider_type_rejected(self):
        """
        Verify that ProviderConfig rejects an invalid provider_type string
        (e.g., 'gemnii' — a typo) with a ValidationError that lists the
        valid enum values.
        """
        with pytest.raises(ValidationError) as exc_info:
            ProviderConfig(provider_type="gemnii")

        error_message = str(exc_info.value)
        # The error message should list the valid ProviderType values
        assert "anthropic" in error_message
        assert "openai_like" in error_message
        assert "gemini" in error_message

    def test_provider_config_missing_provider_type_rejected(self):
        """
        Verify that ProviderConfig rejects a missing provider_type field
        (it is a required field, no default value).
        """
        with pytest.raises(ValidationError) as exc_info:
            ProviderConfig()

        error_message = str(exc_info.value)
        assert "provider_type" in error_message


class TestProviderTypeYamlLoading:
    """Tests for ProviderType validation during YAML config loading."""

    def test_provider_type_yaml_typo_causes_system_exit(self):
        """
        Verify that a YAML config with an invalid provider_type (e.g., 'deepseek')
        causes ConfigLoader.load() to call sys.exit(1) via handle_validation_error.
        """
        mock_yaml_content = """providers:
  typo_provider:
    enabled: true
    provider_type: "deepseek"
    api_base_url: "https://api.deepseek.com/v1"
    access_control:
      gateway_access_token: "test_token"
"""

        with (
            patch("os.path.exists", return_value=True),
            patch("builtins.open", mock_open(read_data=mock_yaml_content)),
        ):
            loader = ConfigLoader(path="dummy_path.yaml")
            # Invalid provider_type triggers ValidationError → handle_validation_error → SystemExit
            with pytest.raises(SystemExit):
                loader.load()

    def test_provider_type_yaml_valid_gemini_loads(self):
        """
        Verify that a YAML config with a valid provider_type ('gemini') loads
        successfully and the provider's provider_type is coerced to ProviderType.GEMINI.
        """
        mock_yaml_content = """providers:
  gemini_provider:
    enabled: true
    provider_type: "gemini"
    api_base_url: "https://generativelanguage.googleapis.com/v1beta"
    access_control:
      gateway_access_token: "test_token"
"""

        with (
            patch("os.path.exists", return_value=True),
            patch("builtins.open", mock_open(read_data=mock_yaml_content)),
        ):
            loader = ConfigLoader(path="dummy_path.yaml")
            config = loader.load()

            provider = config.providers["gemini_provider"]
            assert provider.provider_type == ProviderType.GEMINI
            assert provider.provider_type == "gemini"


class TestProviderTypeSync:
    """Tests for ProviderType ↔ _PROVIDER_CLASSES synchronization."""

    def test_provider_classes_sync_with_provider_type_enum(self):
        """
        Verify that the set of ProviderType enum values exactly matches
        the set of keys in _PROVIDER_CLASSES. This ensures the enum and
        the provider registry stay in sync.
        """
        enum_values = {p.value for p in ProviderType}
        registry_keys = set(_PROVIDER_CLASSES.keys())
        assert enum_values == registry_keys
