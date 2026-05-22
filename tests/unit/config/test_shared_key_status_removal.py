#!/usr/bin/env python3

"""
Test suite for removal of the ``shared_key_status`` field from ``ProviderConfig``.

These tests verify that:
- The ``shared_key_status`` field no longer exists on ``ProviderConfig``
- YAML configs containing ``shared_key_status: true`` are rejected at validation
- YAML configs containing ``shared_key_status: false`` are rejected at validation
- A minimal ``ProviderConfig`` without ``shared_key_status`` is valid

Reference: openspec/changes/remove-shared-key-status/test-plan.md
"""

from unittest.mock import mock_open, patch

import pytest
from pydantic import ValidationError

from src.config.loader import ConfigLoader
from src.config.schemas import ProviderConfig
from src.core.constants import ProviderType


class TestSharedKeyStatusRemoval:
    """Tests verifying that ``shared_key_status`` is fully removed from ``ProviderConfig``."""

    def test_shared_key_status_field_absent_from_schema(self) -> None:
        """
        WHEN the ``ProviderConfig`` Pydantic model is inspected
        THEN no ``shared_key_status`` field SHALL exist on the model.
        """
        assert "shared_key_status" not in ProviderConfig.model_fields, (
            "shared_key_status field should not exist on ProviderConfig, "
            f"but found: {ProviderConfig.model_fields.keys()}"
        )

    def test_yaml_with_shared_key_status_true_rejected(self) -> None:
        """
        YAML files containing ``shared_key_status: true`` SHALL fail validation
        because ``ProviderConfig`` has ``extra='forbid'`` and the field no longer
        exists on the schema.
        """
        mock_yaml_content = """providers:
  test_provider:
    enabled: true
    provider_type: "gemini"
    api_base_url: "https://api.example.com/v1"
    shared_key_status: true
    access_control:
      gateway_access_token: "test_token"
"""

        with (
            patch("os.path.exists", return_value=True),
            patch("builtins.open", mock_open(read_data=mock_yaml_content)),
        ):
            loader = ConfigLoader(path="dummy_path.yaml")
            with pytest.raises(SystemExit):
                loader.load()

    def test_yaml_with_shared_key_status_false_rejected(self) -> None:
        """
        YAML files containing ``shared_key_status: false`` SHALL fail validation
        because ``ProviderConfig`` has ``extra='forbid'`` and the field no longer
        exists on the schema.
        """
        mock_yaml_content = """providers:
  test_provider:
    enabled: true
    provider_type: "gemini"
    api_base_url: "https://api.example.com/v1"
    shared_key_status: false
    access_control:
      gateway_access_token: "test_token"
"""

        with (
            patch("os.path.exists", return_value=True),
            patch("builtins.open", mock_open(read_data=mock_yaml_content)),
        ):
            loader = ConfigLoader(path="dummy_path.yaml")
            with pytest.raises(SystemExit):
                loader.load()


class TestProviderConfigWithoutSharedKeyStatus:
    """Tests verifying ``ProviderConfig`` is valid without ``shared_key_status``."""

    def test_default_config_valid_without_shared_key_status(self) -> None:
        """
        WHEN a minimal ``ProviderConfig`` is constructed with only required fields
        THEN validation SHALL succeed without any ``shared_key_status`` value.
        """
        provider = ProviderConfig(provider_type=ProviderType.GEMINI)

        assert provider.provider_type == ProviderType.GEMINI
        assert provider.enabled is True
        # shared_key_status must not be accessible on the model
        assert "shared_key_status" not in ProviderConfig.model_fields


class TestDirectValidationRejection:
    """Tests that ``shared_key_status`` is rejected at the Pydantic model level."""

    def test_direct_validate_with_shared_key_status_true_rejected(self) -> None:
        """
        WHEN a dict containing ``shared_key_status: true`` is passed to
        ``ProviderConfig.model_validate()``
        THEN a ``ValidationError`` is raised because the field is extra/forbidden.
        """
        data: dict[str, object] = {
            "provider_type": "gemini",
            "shared_key_status": True,
        }

        with pytest.raises(ValidationError) as exc_info:
            ProviderConfig.model_validate(data)

        error_message = str(exc_info.value)
        assert "shared_key_status" in error_message

    def test_direct_validate_with_shared_key_status_false_rejected(self) -> None:
        """
        WHEN a dict containing ``shared_key_status: false`` is passed to
        ``ProviderConfig.model_validate()``
        THEN a ``ValidationError`` is raised because the field is extra/forbidden.
        """
        data: dict[str, object] = {
            "provider_type": "gemini",
            "shared_key_status": False,
        }

        with pytest.raises(ValidationError) as exc_info:
            ProviderConfig.model_validate(data)

        error_message = str(exc_info.value)
        assert "shared_key_status" in error_message

    def test_init_with_shared_key_status_rejected(self) -> None:
        """
        WHEN ``ProviderConfig`` is constructed with ``shared_key_status=True``
        as a keyword argument
        THEN a ``ValidationError`` is raised because the field is extra/forbidden.
        """
        kwargs: dict[str, object] = {
            "provider_type": "gemini",
            "shared_key_status": True,
        }

        with pytest.raises(ValidationError) as exc_info:
            ProviderConfig(**kwargs)  # type: ignore[arg-type]

        error_message = str(exc_info.value)
        assert "shared_key_status" in error_message
