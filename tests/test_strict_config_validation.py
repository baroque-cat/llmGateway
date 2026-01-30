#!/usr/bin/env python3

"""
Test suite for the strict configuration validation feature.
These tests ensure that the ConfigValidator correctly rejects invalid enum values
in the configuration, such as 'diabled' for debug_mode.
"""

import os
import pytest
from unittest.mock import mock_open, patch
from src.config.loader import ConfigLoader
from src.config.validator import ConfigValidator


def test_invalid_debug_mode_should_fail_validation():
    """
    Test that a typo in debug_mode (e.g., 'diabled') causes the ConfigValidator
    to raise a ValueError on startup.
    """
    # Mock YAML content with the typo "diabled"
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

    # Mock the file reading in ConfigLoader
    with patch("os.path.exists", return_value=True), \
         patch("builtins.open", mock_open(read_data=mock_yaml_content)):
        loader = ConfigLoader(path="dummy_path.yaml")
        config = loader.load()

    # Now validate the loaded config
    validator = ConfigValidator()
    
    # The validation should fail with a specific error message
    with pytest.raises(ValueError) as exc_info:
        validator.validate(config)
    
    error_message = str(exc_info.value)
    assert "Invalid debug mode 'diabled'" in error_message
    assert "'disabled'" in error_message  # Should suggest the correct value


def test_invalid_streaming_mode_should_fail_validation():
    """
    Test that an invalid streaming_mode value causes validation to fail.
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

    with patch("os.path.exists", return_value=True), \
         patch("builtins.open", mock_open(read_data=mock_yaml_content)):
        loader = ConfigLoader(path="dummy_path.yaml")
        config = loader.load()

    validator = ConfigValidator()
    
    with pytest.raises(ValueError) as exc_info:
        validator.validate(config)
    
    error_message = str(exc_info.value)
    assert "Invalid streaming mode 'full_stream'" in error_message


def test_invalid_unsafe_mapping_value_should_fail():
    """
    Test that an invalid ErrorReason in unsafe_status_mapping causes validation to fail.
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
      unsafe_status_mapping:
        400: "invalid_typo_reason"  # This ErrorReason doesn't exist
"""

    with patch("os.path.exists", return_value=True), \
         patch("builtins.open", mock_open(read_data=mock_yaml_content)):
        loader = ConfigLoader(path="dummy_path.yaml")
        config = loader.load()

    validator = ConfigValidator()
    
    with pytest.raises(ValueError) as exc_info:
        validator.validate(config)
    
    error_message = str(exc_info.value)
    assert "is not a valid ErrorReason" in error_message
    assert "invalid_typo_reason" in error_message


def test_valid_config_should_pass_validation():
    """
    Ensure that a completely valid configuration passes the new strict validation.
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
      unsafe_status_mapping:
        400: "bad_request"
"""

    with patch("os.path.exists", return_value=True), \
         patch("builtins.open", mock_open(read_data=mock_yaml_content)):
        loader = ConfigLoader(path="dummy_path.yaml")
        config = loader.load()

    validator = ConfigValidator()
    
    # This should not raise any exception
    validator.validate(config)