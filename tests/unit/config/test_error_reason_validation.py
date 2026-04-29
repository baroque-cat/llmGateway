#!/usr/bin/env python3

"""
Test suite for ErrorReason enum validation in configuration schemas.

These tests verify that:
- Valid ErrorReason strings are coerced to enum members in ErrorParsingRule.map_to
- Invalid strings are rejected with ValidationError listing valid values
- Removed fields (fast_status_mapping, error_parsing on gateway_policy) are rejected
- ProviderConfig.error_parsing has correct defaults and is never None
- ErrorParsingRule accepts fulltext mode error_path values ("$" and "")
- YAML loading correctly rejects removed fields and accepts provider-level error_parsing
"""

from unittest.mock import mock_open, patch

import pytest
from pydantic import ValidationError

from src.config.loader import ConfigLoader
from src.config.schemas import (
    ErrorParsingConfig,
    ErrorParsingRule,
    GatewayPolicyConfig,
    HealthPolicyConfig,
    ProviderConfig,
)
from src.core.constants import ErrorReason

# ==============================================================================
# ErrorParsingRule — map_to field validation
# ==============================================================================


def test_error_parsing_rule_map_to_valid_error_reason():
    """
    ErrorParsingRule with a valid ErrorReason string for map_to coerces
    the value to the corresponding ErrorReason enum member.
    """
    rule = ErrorParsingRule(
        status_code=400,
        error_path="error.type",
        match_pattern="INVALID_KEY",
        map_to="invalid_key",
    )
    assert rule.map_to == ErrorReason.INVALID_KEY
    assert isinstance(rule.map_to, ErrorReason)


def test_error_parsing_rule_map_to_invalid_rejected():
    """
    ErrorParsingRule with an invalid string for map_to raises ValidationError.
    The error message should list the valid ErrorReason enum values.
    """
    with pytest.raises(ValidationError) as exc_info:
        ErrorParsingRule(
            status_code=400,
            error_path="e.t",
            match_pattern="x",
            map_to="invald_key",
        )

    error_message = str(exc_info.value)
    # Verify that the error message references valid ErrorReason values
    assert "invalid_key" in error_message
    assert "bad_request" in error_message


def test_error_parsing_rule_map_to_coerces_string_to_enum():
    """
    ErrorParsingRule.map_to accepts the string "rate_limited" and coerces
    it to ErrorReason.RATE_LIMITED enum member.
    """
    rule = ErrorParsingRule(
        status_code=429,
        error_path="e.t",
        match_pattern="x",
        map_to="rate_limited",
    )
    assert rule.map_to == ErrorReason.RATE_LIMITED
    assert isinstance(rule.map_to, ErrorReason)


# ==============================================================================
# CFG-1..CFG-3: Schema rejection of removed fields
# ==============================================================================


def test_gateway_policy_rejects_fast_status_mapping_field():
    """
    CFG-1: GatewayPolicyConfig with extra="forbid" rejects the removed
    fast_status_mapping field, raising ValidationError.
    """
    with pytest.raises(ValidationError) as exc_info:
        GatewayPolicyConfig(fast_status_mapping={400: "bad_request"})

    error_message = str(exc_info.value)
    assert "fast_status_mapping" in error_message


def test_health_policy_rejects_fast_status_mapping_field():
    """
    CFG-2: HealthPolicyConfig with extra="forbid" rejects the removed
    fast_status_mapping field, raising ValidationError.
    """
    with pytest.raises(ValidationError) as exc_info:
        HealthPolicyConfig(fast_status_mapping={400: "bad_request"})

    error_message = str(exc_info.value)
    assert "fast_status_mapping" in error_message


def test_gateway_policy_rejects_error_parsing_field():
    """
    CFG-3: GatewayPolicyConfig with extra="forbid" rejects the error_parsing
    field (moved to ProviderConfig), raising ValidationError.
    """
    with pytest.raises(ValidationError) as exc_info:
        GatewayPolicyConfig(error_parsing=ErrorParsingConfig(enabled=True))

    error_message = str(exc_info.value)
    assert "error_parsing" in error_message


# ==============================================================================
# CFG-4..CFG-5: ProviderConfig.error_parsing defaults
# ==============================================================================


def test_provider_config_error_parsing_default():
    """
    CFG-4: ProviderConfig always contains an error_parsing instance
    via default_factory. The default has enabled=False.
    """
    config = ProviderConfig(provider_type="gemini")
    assert config.error_parsing.enabled is False


def test_provider_config_error_parsing_never_none():
    """
    CFG-5: ProviderConfig.error_parsing is never None — the default_factory
    always produces an ErrorParsingConfig instance.
    """
    config = ProviderConfig(provider_type="gemini")
    assert config.error_parsing is not None
    assert isinstance(config.error_parsing, ErrorParsingConfig)


# ==============================================================================
# CFG-6..CFG-7: ErrorParsingRule fulltext mode error_path
# ==============================================================================


def test_error_parsing_rule_error_path_dollar_accepted():
    """
    CFG-6: ErrorParsingRule accepts error_path="$" (fulltext search mode).
    Pydantic does not raise ValidationError, and the value is stored as-is.
    """
    rule = ErrorParsingRule(
        status_code=400,
        error_path="$",
        match_pattern="RATE_LIMIT",
        map_to="rate_limited",
    )
    assert rule.error_path == "$"


def test_error_parsing_rule_error_path_empty_accepted():
    """
    CFG-7: ErrorParsingRule accepts error_path="" (fulltext search mode,
    equivalent to "$"). Pydantic does not raise ValidationError.
    """
    rule = ErrorParsingRule(
        status_code=400,
        error_path="",
        match_pattern="RATE_LIMIT",
        map_to="rate_limited",
    )
    assert rule.error_path == ""


# ==============================================================================
# CFG-YAML-1..CFG-YAML-4: YAML-level validation
# ==============================================================================


def test_yaml_rejects_gateway_policy_fast_status_mapping():
    """
    CFG-YAML-1: YAML config with gateway_policy.fast_status_mapping
    should fail validation because the field was removed from GatewayPolicyConfig.
    """
    mock_yaml_content = """providers:
  test_provider:
    enabled: true
    provider_type: "gemini"
    api_base_url: "https://api.test.com/v1"
    access_control:
      gateway_access_token: "test_token"
    gateway_policy:
      fast_status_mapping:
        400: "bad_request"
"""

    with (
        patch("os.path.exists", return_value=True),
        patch("builtins.open", mock_open(read_data=mock_yaml_content)),
    ):
        loader = ConfigLoader(path="dummy_path.yaml")
        with pytest.raises(SystemExit):
            loader.load()


def test_yaml_rejects_worker_health_policy_fast_status_mapping():
    """
    CFG-YAML-2: YAML config with worker_health_policy.fast_status_mapping
    should fail validation because the field was removed from HealthPolicyConfig.
    """
    mock_yaml_content = """providers:
  test_provider:
    enabled: true
    provider_type: "gemini"
    api_base_url: "https://api.test.com/v1"
    access_control:
      gateway_access_token: "test_token"
    worker_health_policy:
      fast_status_mapping:
        400: "bad_request"
"""

    with (
        patch("os.path.exists", return_value=True),
        patch("builtins.open", mock_open(read_data=mock_yaml_content)),
    ):
        loader = ConfigLoader(path="dummy_path.yaml")
        with pytest.raises(SystemExit):
            loader.load()


def test_yaml_rejects_gateway_policy_error_parsing():
    """
    CFG-YAML-3: YAML config with gateway_policy.error_parsing should fail
    validation because error_parsing was moved to ProviderConfig and
    GatewayPolicyConfig uses extra="forbid".
    """
    mock_yaml_content = """providers:
  test_provider:
    enabled: true
    provider_type: "gemini"
    api_base_url: "https://api.test.com/v1"
    access_control:
      gateway_access_token: "test_token"
    gateway_policy:
      error_parsing:
        enabled: true
"""

    with (
        patch("os.path.exists", return_value=True),
        patch("builtins.open", mock_open(read_data=mock_yaml_content)),
    ):
        loader = ConfigLoader(path="dummy_path.yaml")
        with pytest.raises(SystemExit):
            loader.load()


def test_yaml_accepts_provider_level_error_parsing():
    """
    CFG-YAML-4: YAML config with error_parsing at the provider level
    should load successfully, with error_parsing.enabled=True and rules
    correctly loaded.
    """
    mock_yaml_content = """providers:
  test_provider:
    enabled: true
    provider_type: "gemini"
    api_base_url: "https://api.test.com/v1"
    access_control:
      gateway_access_token: "test_token"
    error_parsing:
      enabled: true
      rules:
        - status_code: 400
          error_path: "error.type"
          match_pattern: "Arrearage"
          map_to: "no_quota"
"""

    with (
        patch("os.path.exists", return_value=True),
        patch("builtins.open", mock_open(read_data=mock_yaml_content)),
    ):
        loader = ConfigLoader(path="dummy_path.yaml")
        config = loader.load()

        provider = config.providers["test_provider"]
        assert provider.error_parsing.enabled is True
        assert len(provider.error_parsing.rules) == 1
        assert provider.error_parsing.rules[0].map_to == ErrorReason.NO_QUOTA
