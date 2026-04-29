#!/usr/bin/env python3

"""
Test suite for ErrorReason enum validation in configuration schemas.

Group G5 tests: 16 scenarios covering ErrorReason coercion and rejection
in ErrorParsingRule.map_to, HealthPolicyConfig.fast_status_mapping,
GatewayPolicyConfig.fast_status_mapping, and YAML-based loading.

These tests verify that:
- Valid ErrorReason strings are coerced to enum members
- Invalid strings are rejected with ValidationError listing valid values
- HTTP status code keys in fast_status_mapping are validated (100–599)
- Empty fast_status_mapping dicts are accepted
- YAML loading correctly coerces valid values and SystemExits on invalid ones
"""

from unittest.mock import mock_open, patch

import pytest
from pydantic import ValidationError

from src.config.loader import ConfigLoader
from src.config.schemas import (
    ErrorParsingRule,
    GatewayPolicyConfig,
    HealthPolicyConfig,
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
# HealthPolicyConfig — fast_status_mapping validation
# ==============================================================================


def test_health_policy_fast_status_mapping_valid_error_reason():
    """
    HealthPolicyConfig.fast_status_mapping accepts valid ErrorReason strings
    and coerces them to ErrorReason enum members.
    """
    policy = HealthPolicyConfig(
        fast_status_mapping={400: "bad_request", 429: "rate_limited"}
    )
    assert policy.fast_status_mapping[400] == ErrorReason.BAD_REQUEST
    assert policy.fast_status_mapping[429] == ErrorReason.RATE_LIMITED
    assert isinstance(policy.fast_status_mapping[400], ErrorReason)
    assert isinstance(policy.fast_status_mapping[429], ErrorReason)


def test_health_policy_fast_status_mapping_invalid_value_rejected():
    """
    HealthPolicyConfig.fast_status_mapping rejects invalid ErrorReason strings
    with a ValidationError.
    """
    with pytest.raises(ValidationError) as exc_info:
        HealthPolicyConfig(fast_status_mapping={400: "garbage"})

    error_message = str(exc_info.value)
    assert "garbage" in error_message


def test_health_policy_fast_status_mapping_key_below_100_rejected():
    """
    HealthPolicyConfig.fast_status_mapping rejects keys below 100.
    The model_validator raises ValueError (wrapped in ValidationError by Pydantic)
    because HTTP status codes must be in range 100–599.
    """
    with pytest.raises(ValidationError) as exc_info:
        HealthPolicyConfig(fast_status_mapping={99: "bad_request"})

    error_message = str(exc_info.value)
    assert "99" in error_message


def test_health_policy_fast_status_mapping_key_600_rejected():
    """
    HealthPolicyConfig.fast_status_mapping rejects key 600.
    The valid range is 100–599 (inclusive), so 600 is out of range.
    """
    with pytest.raises(ValidationError) as exc_info:
        HealthPolicyConfig(fast_status_mapping={600: "server_error"})

    error_message = str(exc_info.value)
    assert "600" in error_message


def test_health_policy_fast_status_mapping_key_100_valid():
    """
    HealthPolicyConfig.fast_status_mapping accepts key 100 (lower boundary).
    The valid range is 100 <= key < 600.
    """
    policy = HealthPolicyConfig(fast_status_mapping={100: "bad_request"})
    assert 100 in policy.fast_status_mapping
    assert policy.fast_status_mapping[100] == ErrorReason.BAD_REQUEST


def test_health_policy_fast_status_mapping_key_599_valid():
    """
    HealthPolicyConfig.fast_status_mapping accepts key 599 (upper boundary).
    The valid range is 100 <= key < 600.
    """
    policy = HealthPolicyConfig(fast_status_mapping={599: "server_error"})
    assert 599 in policy.fast_status_mapping
    assert policy.fast_status_mapping[599] == ErrorReason.SERVER_ERROR


def test_health_policy_fast_status_mapping_key_999_rejected():
    """
    HealthPolicyConfig.fast_status_mapping rejects key 999.
    999 is well outside the valid HTTP status code range 100–599.
    """
    with pytest.raises(ValidationError) as exc_info:
        HealthPolicyConfig(fast_status_mapping={999: "server_error"})

    error_message = str(exc_info.value)
    assert "999" in error_message


# ==============================================================================
# GatewayPolicyConfig — fast_status_mapping validation
# ==============================================================================


def test_gateway_policy_fast_status_mapping_valid_error_reason():
    """
    GatewayPolicyConfig.fast_status_mapping accepts valid ErrorReason strings
    and coerces them to ErrorReason enum members.
    """
    policy = GatewayPolicyConfig(fast_status_mapping={500: "server_error"})
    assert policy.fast_status_mapping[500] == ErrorReason.SERVER_ERROR
    assert isinstance(policy.fast_status_mapping[500], ErrorReason)


def test_gateway_policy_fast_status_mapping_invalid_value_rejected():
    """
    GatewayPolicyConfig.fast_status_mapping rejects invalid ErrorReason strings
    with a ValidationError.
    """
    with pytest.raises(ValidationError) as exc_info:
        GatewayPolicyConfig(fast_status_mapping={400: "not_a_reason"})

    error_message = str(exc_info.value)
    assert "not_a_reason" in error_message


def test_gateway_policy_fast_status_mapping_key_out_of_range_rejected():
    """
    GatewayPolicyConfig.fast_status_mapping rejects keys outside 100–599 range.
    Key 999 triggers the model_validator ValueError (wrapped in ValidationError).
    """
    with pytest.raises(ValidationError) as exc_info:
        GatewayPolicyConfig(fast_status_mapping={999: "server_error"})

    error_message = str(exc_info.value)
    assert "999" in error_message


def test_gateway_policy_fast_status_mapping_empty_dict_valid():
    """
    GatewayPolicyConfig.fast_status_mapping accepts an empty dict.
    No keys to validate, so the model_validator passes trivially.
    """
    policy = GatewayPolicyConfig(fast_status_mapping={})
    assert policy.fast_status_mapping == {}


# ==============================================================================
# YAML-based loading — fast_status_mapping integration
# ==============================================================================


def test_fast_status_mapping_yaml_valid_loads():
    """
    YAML config with valid fast_status_mapping entries loads successfully
    through ConfigLoader, and values are coerced to ErrorReason enum members.
    """
    mock_yaml_content = """providers:
  test_provider:
    enabled: true
    provider_type: "gemini"
    keys_path: "keys/test/"
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
        config = loader.load()

        provider = config.providers["test_provider"]
        assert (
            provider.gateway_policy.fast_status_mapping[400] == ErrorReason.BAD_REQUEST
        )


def test_fast_status_mapping_yaml_invalid_value_system_exit():
    """
    YAML config with an invalid ErrorReason string in fast_status_mapping
    causes ConfigLoader.load() to call sys.exit(1) via handle_validation_error.
    """
    mock_yaml_content = """providers:
  test_provider:
    enabled: true
    provider_type: "gemini"
    keys_path: "keys/test/"
    api_base_url: "https://api.test.com/v1"
    access_control:
      gateway_access_token: "test_token"
    gateway_policy:
      fast_status_mapping:
        400: "garbage"
"""

    with (
        patch("os.path.exists", return_value=True),
        patch("builtins.open", mock_open(read_data=mock_yaml_content)),
    ):
        loader = ConfigLoader(path="dummy_path.yaml")
        with pytest.raises(SystemExit):
            loader.load()
