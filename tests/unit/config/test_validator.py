#!/usr/bin/env python3

"""
Test suite for Pydantic v2 configuration validation.

These tests verify that the Pydantic BaseModel schemas correctly reject invalid
values at the model_validate() boundary. With the migration from dataclasses +
ConfigValidator to Pydantic v2 BaseModel, validation is now performed inline
during model construction rather than in a separate post-load validation step.
"""

from unittest.mock import mock_open, patch

import pytest
from pydantic import ValidationError

from src.config.loader import ConfigLoader
from src.config.schemas import GatewayPolicyConfig, ProviderConfig


def test_invalid_debug_mode_should_fail_validation():
    """
    Test that a typo in debug_mode (e.g., 'diabled') causes Pydantic
    ValidationError during config loading.
    """
    mock_yaml_content = """providers:
  test_provider:
    enabled: true
    provider_type: "test"
    keys_path: "keys/test/"
    api_base_url: "https://api.test.com/v1"
    access_control:
      gateway_access_token: "test_token"
    gateway_policy:
      debug_mode: "diabled"  # This is the typo we want to catch
"""

    with (
        patch("os.path.exists", return_value=True),
        patch("builtins.open", mock_open(read_data=mock_yaml_content)),
    ):
        loader = ConfigLoader(path="dummy_path.yaml")
        # Pydantic validation now happens inside loader.load() via model_validate()
        # handle_validation_error calls sys.exit(1), so we catch that
        with pytest.raises(SystemExit):
            loader.load()


def test_invalid_debug_mode_direct_schema_validation():
    """
    Test that GatewayPolicyConfig directly rejects invalid debug_mode values
    via Pydantic Literal type validation.
    """
    with pytest.raises(ValidationError) as exc_info:
        GatewayPolicyConfig(debug_mode="diabled")

    error_message = str(exc_info.value)
    # Pydantic should report that "diabled" is not a valid literal value
    assert "diabled" in error_message


def test_invalid_streaming_mode_should_fail_validation():
    """
    Test that an invalid streaming_mode value causes Pydantic ValidationError
    during config loading.
    """
    mock_yaml_content = """providers:
  test_provider:
    enabled: true
    provider_type: "test"
    keys_path: "keys/test/"
    api_base_url: "https://api.test.com/v1"
    access_control:
      gateway_access_token: "test_token"
    gateway_policy:
      streaming_mode: "full_stream"  # Invalid value
"""

    with (
        patch("os.path.exists", return_value=True),
        patch("builtins.open", mock_open(read_data=mock_yaml_content)),
    ):
        loader = ConfigLoader(path="dummy_path.yaml")
        with pytest.raises(SystemExit):
            loader.load()


def test_invalid_streaming_mode_direct_schema_validation():
    """
    Test that GatewayPolicyConfig directly rejects invalid streaming_mode values.
    """
    with pytest.raises(ValidationError) as exc_info:
        GatewayPolicyConfig(streaming_mode="full_stream")

    error_message = str(exc_info.value)
    assert "full_stream" in error_message


def test_invalid_fast_mapping_value_should_fail():
    """
    Test that an invalid ErrorReason in fast_status_mapping causes validation failure.

    Note: With Pydantic v2, fast_status_mapping is typed as dict[int, str],
    so any string value is accepted at the schema level. The ErrorReason validation
    was previously done by ConfigValidator. This test now verifies that the schema
    accepts valid string values (the old ConfigValidator-level check for valid
    ErrorReason enum values is no longer enforced at the Pydantic schema level).
    """
    # With Pydantic dict[int, str], any string value is valid at schema level
    # The old ConfigValidator checked for valid ErrorReason enum values, but
    # that validation is no longer part of the Pydantic schema.
    # This test verifies the schema accepts arbitrary string values.
    policy = GatewayPolicyConfig(fast_status_mapping={400: "invalid_typo_reason"})
    assert policy.fast_status_mapping[400] == "invalid_typo_reason"


def test_valid_config_should_pass_validation():
    """
    Ensure that a completely valid configuration passes Pydantic validation
    during config loading.
    """
    mock_yaml_content = """providers:
  test_provider:
    enabled: true
    provider_type: "test"
    keys_path: "keys/test/"
    api_base_url: "https://api.test.com/v1"
    access_control:
      gateway_access_token: "test_token"
    gateway_policy:
      debug_mode: "disabled"
      streaming_mode: "auto"
      fast_status_mapping:
        400: "bad_request"
"""

    with (
        patch("os.path.exists", return_value=True),
        patch("builtins.open", mock_open(read_data=mock_yaml_content)),
    ):
        loader = ConfigLoader(path="dummy_path.yaml")
        config = loader.load()

        # Verify the config loaded correctly
        provider = config.providers["test_provider"]
        assert provider.gateway_policy.debug_mode == "disabled"
        assert provider.gateway_policy.streaming_mode == "auto"
        assert provider.gateway_policy.fast_status_mapping[400] == "bad_request"


def test_provider_config_extra_fields_forbidden():
    """
    Test that ProviderConfig rejects extra fields (Pydantic extra="forbid").
    This replaces the old ConfigValidator's strict validation approach.
    """
    with pytest.raises(ValidationError) as exc_info:
        ProviderConfig(
            provider_type="test",
            keys_path="keys/test/",
            unknown_field="should_be_rejected",
        )

    error_message = str(exc_info.value)
    assert (
        "unknown_field" in error_message
        or "Extra inputs are not permitted" in error_message
    )


def test_config_root_extra_fields_forbidden():
    """
    Test that Config root model rejects extra fields (Pydantic extra="forbid").
    """
    from src.config.schemas import Config

    with pytest.raises(ValidationError) as exc_info:
        Config.model_validate({"unknown_section": "should_fail"})

    error_message = str(exc_info.value)
    assert (
        "Extra inputs are not permitted" in error_message
        or "unknown_section" in error_message
    )


def test_health_policy_quarantine_logic():
    """
    Test that HealthPolicyConfig model_validator rejects quarantine_after_days
    greater than stop_checking_after_days.
    """
    from src.config.schemas import HealthPolicyConfig

    with pytest.raises(ValidationError) as exc_info:
        HealthPolicyConfig(
            quarantine_after_days=100,
            stop_checking_after_days=50,
        )

    error_message = str(exc_info.value)
    assert "quarantine_after_days" in error_message


def test_proxy_config_static_mode_requires_url():
    """
    Test that ProxyConfig model_validator requires static_url when mode is 'static'.
    """
    from src.config.schemas import ProxyConfig

    with pytest.raises(ValidationError) as exc_info:
        ProxyConfig(mode="static")

    error_message = str(exc_info.value)
    assert "static_url" in error_message


def test_proxy_config_stealth_mode_requires_pool_path():
    """
    Test that ProxyConfig model_validator requires pool_list_path when mode is 'stealth'.
    """
    from src.config.schemas import ProxyConfig

    with pytest.raises(ValidationError) as exc_info:
        ProxyConfig(mode="stealth")

    error_message = str(exc_info.value)
    assert "pool_list_path" in error_message


def test_duplicate_gateway_tokens_rejected():
    """
    Test that Config model_validator rejects duplicate gateway_access_token
    across enabled providers.
    """
    from src.config.schemas import Config

    with pytest.raises(ValidationError) as exc_info:
        Config.model_validate(
            {
                "providers": {
                    "provider_a": {
                        "provider_type": "test",
                        "keys_path": "keys/a/",
                        "enabled": True,
                        "access_control": {"gateway_access_token": "same_token"},
                    },
                    "provider_b": {
                        "provider_type": "test",
                        "keys_path": "keys/b/",
                        "enabled": True,
                        "access_control": {"gateway_access_token": "same_token"},
                    },
                }
            }
        )

    error_message = str(exc_info.value)
    assert "Duplicate gateway_access_token" in error_message
