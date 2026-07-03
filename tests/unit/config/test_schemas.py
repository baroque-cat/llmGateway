#!/usr/bin/env python3

"""
Test suite for ProviderConfig.max_concurrent_streams_per_connection field.

Covers two spec capabilities:
  - h2-stream-cap: Per-provider max_concurrent_streams cap (default, custom, bounds)
  - http-client-pool-config: Per-provider max_concurrent_streams_per_connection
    field (field default, field set in YAML, field validates bounds, field
    rejects values above 1000)

Tests 1-3 exercise the field through YAML config loading via ConfigLoader.
Tests 4-7 exercise the field directly through ProviderConfig schema construction.
"""

from unittest.mock import mock_open, patch

import pytest
from pydantic import ValidationError

from src.config.loader import ConfigLoader
from src.config.schemas import ProviderConfig

# ==============================================================================
# h2-stream-cap: Per-provider max_concurrent_streams cap (YAML loading)
# ==============================================================================


def test_max_concurrent_streams_default_is_5():
    """Default cap of 5 applied when the field is absent from YAML.

    Args:
        None — uses mocked YAML content.

    Returns:
        None — asserts the loaded provider has the default cap of 5.
    """
    mock_yaml_content = """providers:
  test_provider:
    enabled: true
    provider_type: "openai_like"
    api_base_url: "https://api.test.com/v1"
    access_control:
      gateway_access_token: "test_token"
"""

    with (
        patch("os.path.exists", return_value=True),
        patch("builtins.open", mock_open(read_data=mock_yaml_content)),
    ):
        loader = ConfigLoader(path="dummy_path.yaml")
        config = loader.load()

        provider = config.providers["test_provider"]
        assert provider.max_concurrent_streams_per_connection == 5


def test_max_concurrent_streams_custom_value():
    """Custom cap from YAML is loaded and applied to the provider.

    Args:
        None — uses mocked YAML content with a custom cap of 42.

    Returns:
        None — asserts the loaded provider has the custom cap of 42.
    """
    mock_yaml_content = """providers:
  test_provider:
    enabled: true
    provider_type: "openai_like"
    api_base_url: "https://api.test.com/v1"
    access_control:
      gateway_access_token: "test_token"
    max_concurrent_streams_per_connection: 42
"""

    with (
        patch("os.path.exists", return_value=True),
        patch("builtins.open", mock_open(read_data=mock_yaml_content)),
    ):
        loader = ConfigLoader(path="dummy_path.yaml")
        config = loader.load()

        provider = config.providers["test_provider"]
        assert provider.max_concurrent_streams_per_connection == 42


def test_max_concurrent_streams_rejects_zero():
    """Cap validates bounds — zero is rejected during YAML loading.

    A value of 0 violates the ge=1 constraint, causing a ValidationError
    that ConfigLoader converts to SystemExit.

    Args:
        None — uses mocked YAML content with cap of 0.

    Returns:
        None — asserts that SystemExit is raised.
    """
    mock_yaml_content = """providers:
  test_provider:
    enabled: true
    provider_type: "openai_like"
    api_base_url: "https://api.test.com/v1"
    access_control:
      gateway_access_token: "test_token"
    max_concurrent_streams_per_connection: 0
"""

    with (
        patch("os.path.exists", return_value=True),
        patch("builtins.open", mock_open(read_data=mock_yaml_content)),
    ):
        loader = ConfigLoader(path="dummy_path.yaml")
        with pytest.raises(SystemExit):
            loader.load()


# ==============================================================================
# http-client-pool-config: Per-provider field (direct schema construction)
# ==============================================================================


def test_max_concurrent_streams_field_defaults_to_5():
    """Field defaults to 5 when ProviderConfig is constructed without it.

    Args:
        None — constructs ProviderConfig directly.

    Returns:
        None — asserts the field equals 5.
    """
    provider = ProviderConfig(provider_type="openai_like")
    assert provider.max_concurrent_streams_per_connection == 5


def test_max_concurrent_streams_field_set_in_yaml():
    """Field set in YAML — explicit value is honored by the schema.

    Constructs ProviderConfig directly with an explicit cap to verify the
    field accepts and stores custom values.

    Args:
        None — constructs ProviderConfig directly.

    Returns:
        None — asserts the field equals the provided value.
    """
    provider = ProviderConfig(
        provider_type="openai_like",
        max_concurrent_streams_per_connection=42,
    )
    assert provider.max_concurrent_streams_per_connection == 42


def test_max_concurrent_streams_field_rejects_zero():
    """Field validates bounds — zero is rejected by the schema (ge=1).

    Args:
        None — constructs ProviderConfig directly with cap of 0.

    Returns:
        None — asserts that ValidationError is raised.
    """
    with pytest.raises(ValidationError) as exc_info:
        ProviderConfig(
            provider_type="openai_like",
            max_concurrent_streams_per_connection=0,
        )

    error_message = str(exc_info.value)
    assert "max_concurrent_streams_per_connection" in error_message


def test_max_concurrent_streams_field_rejects_above_1000():
    """Field rejects values above 1000 (le=1000 constraint).

    Args:
        None — constructs ProviderConfig directly with cap of 1001.

    Returns:
        None — asserts that ValidationError is raised.
    """
    with pytest.raises(ValidationError) as exc_info:
        ProviderConfig(
            provider_type="openai_like",
            max_concurrent_streams_per_connection=1001,
        )

    error_message = str(exc_info.value)
    assert "max_concurrent_streams_per_connection" in error_message
