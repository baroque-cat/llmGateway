#!/usr/bin/env python3

"""
Unit tests for metrics configuration.

Tests MetricsConfig defaults, validation, and YAML loading.
"""

from unittest.mock import mock_open, patch

from src.config.loader import ConfigLoader
from src.config.schemas import Config, MetricsConfig


class TestMetricsConfig:
    """Test MetricsConfig dataclass."""

    def test_default_values(self):
        """Test MetricsConfig default values."""
        config = MetricsConfig()
        assert config.enabled is True  # According to schema, default is True
        assert config.access_token == ""

    def test_custom_values(self):
        """Test MetricsConfig with custom values."""
        config = MetricsConfig(enabled=False, access_token="secret-token")
        assert config.enabled is False
        assert config.access_token == "secret-token"

    def test_empty_token_when_enabled(self):
        """Test MetricsConfig can have empty token even when enabled."""
        config = MetricsConfig(enabled=True, access_token="")
        assert config.enabled is True
        assert config.access_token == ""

    def test_token_whitespace_handling(self):
        """Test token with whitespace is preserved as-is."""
        config = MetricsConfig(access_token="  token with spaces  ")
        assert config.access_token == "  token with spaces  "


class TestMetricsConfigYamlLoading:
    """Test loading metrics configuration from YAML."""

    def test_metrics_section_defaults(self):
        """Test that missing metrics section uses defaults."""
        yaml_content = """providers: {}
logging: {}
"""
        with (
            patch("os.path.exists", return_value=True),
            patch("builtins.open", mock_open(read_data=yaml_content)),
        ):
            loader = ConfigLoader(path="dummy.yaml")
            config = loader.load()

            # Metrics config should exist with defaults
            assert hasattr(config, "metrics")
            assert config.metrics.enabled is True  # Default per schema
            assert config.metrics.access_token == ""

    def test_metrics_section_explicit(self):
        """Test explicit metrics configuration in YAML."""
        yaml_content = """
providers: {}
logging: {}
metrics:
  enabled: false
  access_token: "my-secret-token"
"""
        with (
            patch("os.path.exists", return_value=True),
            patch("builtins.open", mock_open(read_data=yaml_content)),
        ):
            loader = ConfigLoader(path="dummy.yaml")
            config = loader.load()

            assert config.metrics.enabled is False
            assert config.metrics.access_token == "my-secret-token"

    def test_metrics_partial_configuration(self):
        """Test partial metrics configuration (only enabled)."""
        yaml_content = """
providers: {}
logging: {}
metrics:
  enabled: true
"""
        with (
            patch("os.path.exists", return_value=True),
            patch("builtins.open", mock_open(read_data=yaml_content)),
        ):
            loader = ConfigLoader(path="dummy.yaml")
            config = loader.load()

            assert config.metrics.enabled is True
            assert config.metrics.access_token == ""  # Default empty string

    def test_metrics_empty_object(self):
        """Test empty metrics object in YAML."""
        yaml_content = """
providers: {}
logging: {}
metrics: {}
"""
        with (
            patch("os.path.exists", return_value=True),
            patch("builtins.open", mock_open(read_data=yaml_content)),
        ):
            loader = ConfigLoader(path="dummy.yaml")
            config = loader.load()

            # Should use defaults
            assert config.metrics.enabled is True
            assert config.metrics.access_token == ""

    def test_metrics_disabled_without_token(self):
        """Test metrics can be disabled without providing token."""
        yaml_content = """
providers: {}
logging: {}
metrics:
  enabled: false
"""
        with (
            patch("os.path.exists", return_value=True),
            patch("builtins.open", mock_open(read_data=yaml_content)),
        ):
            loader = ConfigLoader(path="dummy.yaml")
            config = loader.load()

            assert config.metrics.enabled is False
            assert config.metrics.access_token == ""

    def test_root_config_with_metrics(self):
        """Test Config includes metrics section."""
        config = Config()
        assert hasattr(config, "metrics")
        assert isinstance(config.metrics, MetricsConfig)
        assert config.metrics.enabled is True
        assert config.metrics.access_token == ""


class TestMetricsConfigIntegration:
    """Integration tests for metrics configuration usage."""

    def test_accessor_get_metrics_config(self):
        """Test ConfigAccessor.get_metrics_config returns correct config."""
        from src.core.accessor import ConfigAccessor

        # Create a mock root config
        root_config = Config()
        root_config.metrics.enabled = False
        root_config.metrics.access_token = "test-token"

        accessor = ConfigAccessor(root_config)
        metrics_config = accessor.get_metrics_config()

        assert metrics_config.enabled is False
        assert metrics_config.access_token == "test-token"
        assert metrics_config is root_config.metrics

    def test_metrics_config_immutability(self):
        """Test that metrics config can't be accidentally modified via accessor."""
        from src.core.accessor import ConfigAccessor

        root_config = Config()
        root_config.metrics.enabled = True
        root_config.metrics.access_token = "original"

        accessor = ConfigAccessor(root_config)
        metrics_config = accessor.get_metrics_config()

        # Modify the returned object (should affect root config since it's a reference)
        metrics_config.access_token = "modified"

        # Verify root config was modified (since it's the same object)
        assert root_config.metrics.access_token == "modified"
