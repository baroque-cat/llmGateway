#!/usr/bin/env python3

"""
Unit tests for ConfigLoader.load() method.
"""

from unittest.mock import mock_open, patch

import pytest
from ruamel.yaml.error import YAMLError

from src.config.loader import ConfigLoader


def test_config_loader_load_success():
    """
    Test that ConfigLoader.load() successfully loads a valid YAML configuration.
    """
    mock_yaml_content = """database:
  host: localhost
  port: 5432
  password: test_password
worker:
  max_concurrent_providers: 5
providers:
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
"""

    with (
        patch("os.path.exists", return_value=True),
        patch("builtins.open", mock_open(read_data=mock_yaml_content)),
    ):
        loader = ConfigLoader(path="dummy_path.yaml")
        config = loader.load()

        # Verify basic structure
        assert config.database.host == "localhost"
        assert config.database.port == 5432
        assert config.worker.max_concurrent_providers == 5
        assert "test_provider" in config.providers
        provider = config.providers["test_provider"]
        assert provider.enabled is True
        assert provider.provider_type == "test"
        assert provider.api_base_url == "https://api.test.com/v1"


def test_config_loader_file_not_found():
    """
    Test that ConfigLoader.load() raises FileNotFoundError when the file does not exist.
    """
    with patch("os.path.exists", return_value=False):
        loader = ConfigLoader(path="nonexistent.yaml")
        with pytest.raises(FileNotFoundError):
            loader.load()


def test_config_loader_invalid_yaml():
    """
    Test that ConfigLoader.load() raises YAMLError when the file contains invalid YAML.
    """
    invalid_yaml_content = "invalid: [unclosed bracket"

    with (
        patch("os.path.exists", return_value=True),
        patch("builtins.open", mock_open(read_data=invalid_yaml_content)),
    ):
        loader = ConfigLoader(path="invalid.yaml")
        with pytest.raises(YAMLError):
            loader.load()


def test_config_loader_amnesty_threshold_field():
    """
    Test that the amnesty_threshold_days field in worker_health_policy is correctly loaded.
    """
    mock_yaml_content = """database:
  host: localhost
  port: 5432
  password: test_password
worker:
  max_concurrent_providers: 5
providers:
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
    worker_health_policy:
      amnesty_threshold_days: 3.5
"""

    with (
        patch("os.path.exists", return_value=True),
        patch("builtins.open", mock_open(read_data=mock_yaml_content)),
    ):
        loader = ConfigLoader(path="dummy_path.yaml")
        config = loader.load()

        # Verify amnesty_threshold_days is loaded correctly
        provider = config.providers["test_provider"]
        assert provider.worker_health_policy.amnesty_threshold_days == 3.5
        # Ensure other default values are still present
        assert provider.worker_health_policy.quarantine_after_days == 30
        assert provider.worker_health_policy.on_success_hr == 24  # from defaults
