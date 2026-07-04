#!/usr/bin/env python3

"""
Unit tests for ConfigLoader.load() method.
"""

import os
from unittest.mock import mock_open, patch

import pytest
from ruamel.yaml.error import YAMLError

from src.config.loader import ConfigLoader
from tests._canonical import CanonicalConfig

# Canonical env vars from .env.example + config/example_full_config.yaml
_BASE_ENV: dict[str, str] = CanonicalConfig.from_example_files().to_env_dict()


def test_config_loader_load_success():
    """
    Test that ConfigLoader.load() successfully loads a valid YAML configuration.
    """
    mock_yaml_content = """database:
  host: localhost
  port: 5432
  password: test_password
keeper:
  max_concurrent_providers: 5
providers:
  test_provider:
    enabled: true
    provider_type: "gemini"
    api_base_url: "https://api.test.com/v1"
    access_control:
      gateway_access_token: "test_token"
    gateway_policy:
      debug_mode: "disabled"
      streaming_mode: "auto"
"""

    with (
        patch.dict(os.environ, _BASE_ENV),
        patch("os.path.exists", return_value=True),
        patch("builtins.open", mock_open(read_data=mock_yaml_content)),
    ):
        loader = ConfigLoader(path="dummy_path.yaml")
        config = loader.load()

        # Verify basic structure
        assert config.database.host == "localhost"
        assert config.database.port == 5432
        assert config.keeper.max_concurrent_providers == 5
        assert "test_provider" in config.providers
        provider = config.providers["test_provider"]
        assert provider.enabled is True
        assert provider.provider_type == "gemini"
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
keeper:
  max_concurrent_providers: 5
providers:
  test_provider:
    enabled: true
    provider_type: "gemini"
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
        patch.dict(os.environ, _BASE_ENV),
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
        assert provider.worker_health_policy.task_timeout_sec == 900  # from defaults


def test_config_loader_task_timeout_field():
    """
    Test that the task_timeout_sec field in worker_health_policy is correctly loaded.
    """
    mock_yaml_content = """database:
  host: localhost
  port: 5432
  password: test_password
keeper:
  max_concurrent_providers: 5
providers:
  test_provider:
    enabled: true
    provider_type: "gemini"
    api_base_url: "https://api.test.com/v1"
    access_control:
      gateway_access_token: "test_token"
    gateway_policy:
      debug_mode: "disabled"
      streaming_mode: "auto"
    worker_health_policy:
      task_timeout_sec: 600
"""

    with (
        patch.dict(os.environ, _BASE_ENV),
        patch("os.path.exists", return_value=True),
        patch("builtins.open", mock_open(read_data=mock_yaml_content)),
    ):
        loader = ConfigLoader(path="dummy_path.yaml")
        config = loader.load()

        # Verify task_timeout_sec is loaded correctly
        provider = config.providers["test_provider"]
        assert provider.worker_health_policy.task_timeout_sec == 600
        # Ensure other default values are still present
        assert provider.worker_health_policy.amnesty_threshold_days == 2.0
        assert provider.worker_health_policy.adaptive_batching.start_batch_size == 10


def test_load_yaml_with_explicit_adaptive_batching_values():
    """
    Test that explicit adaptive_batching values in YAML are loaded correctly
    and match the new defaults: start_batch_size=10, start_batch_delay_sec=30.0.
    """
    mock_yaml_content = """database:
  host: localhost
  port: 5432
  password: test_password
keeper:
  max_concurrent_providers: 5
providers:
  test_provider:
    enabled: true
    provider_type: "gemini"
    api_base_url: "https://api.test.com/v1"
    access_control:
      gateway_access_token: "test_token"
    gateway_policy:
      debug_mode: "disabled"
      streaming_mode: "auto"
    worker_health_policy:
      adaptive_batching:
        start_batch_size: 10
        start_batch_delay_sec: 30.0
"""

    with (
        patch.dict(os.environ, _BASE_ENV),
        patch("os.path.exists", return_value=True),
        patch("builtins.open", mock_open(read_data=mock_yaml_content)),
    ):
        loader = ConfigLoader(path="dummy_path.yaml")
        config = loader.load()

        provider = config.providers["test_provider"]
        adaptive = provider.worker_health_policy.adaptive_batching

        # Verify the explicit adaptive batching values
        assert adaptive.start_batch_size == 10
        assert adaptive.start_batch_delay_sec == 30.0

        # Verify other adaptive batching defaults remain intact
        assert adaptive.min_batch_size == 5
        assert adaptive.max_batch_size == 50
        assert adaptive.min_batch_delay_sec == 3.0
        assert adaptive.max_batch_delay_sec == 120.0
        assert adaptive.failure_rate_threshold == 0.3
