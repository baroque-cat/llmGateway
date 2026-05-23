#!/usr/bin/env python3

"""
Unit tests for HttpClientPoolConfig, HttpClientConfig, and
HttpClientLoggingConfig Pydantic schemas.

Tests cover defaults, validation, bounds checking, YAML loading via
ConfigLoader, and integration with the root Config model.

Test IDs:
  UT-HC01..UT-HC20 — Functional tests for HTTP client config models
"""

from unittest.mock import mock_open, patch

import pytest
from pydantic import ValidationError

from src.config.loader import ConfigLoader
from src.config.schemas import (
    Config,
    HttpClientConfig,
    HttpClientLoggingConfig,
    HttpClientPoolConfig,
)

# ==============================================================================
# UT-HC01..UT-HC03: Default values for HttpClientPoolConfig
# ==============================================================================


class TestHttpClientPoolConfigDefaults:
    """Test HttpClientPoolConfig default values and basic construction."""

    def test_ut_hc01_default_values(self):
        """UT-HC01: HttpClientPoolConfig() → max_connections=100,
        max_keepalive_connections=20, keepalive_expiry=5.0."""
        pool = HttpClientPoolConfig()
        assert pool.max_connections == 100
        assert pool.max_keepalive_connections == 20
        assert pool.keepalive_expiry == 5.0

    def test_ut_hc02_custom_values(self):
        """UT-HC02: HttpClientPoolConfig(max_connections=200,
        max_keepalive_connections=50, keepalive_expiry=30.0) → values match."""
        pool = HttpClientPoolConfig(
            max_connections=200,
            max_keepalive_connections=50,
            keepalive_expiry=30.0,
        )
        assert pool.max_connections == 200
        assert pool.max_keepalive_connections == 50
        assert pool.keepalive_expiry == pytest.approx(30.0)

    def test_ut_hc03_all_fields_explicit(self):
        """UT-HC03: HttpClientPoolConfig with all fields explicit → matches."""
        pool = HttpClientPoolConfig(
            max_connections=150,
            max_keepalive_connections=25,
            keepalive_expiry=10.0,
        )
        assert pool.max_connections == 150
        assert pool.max_keepalive_connections == 25
        assert pool.keepalive_expiry == pytest.approx(10.0)


# ==============================================================================
# UT-HC04..UT-HC05: Default values for HttpClientConfig
# ==============================================================================


class TestHttpClientConfigDefaults:
    """Test HttpClientConfig default values and nested pool defaults."""

    def test_ut_hc04_default_values(self):
        """UT-HC04: HttpClientConfig() → http2=True, pool has defaults
        (max_connections=100, max_keepalive_connections=20, keepalive_expiry=5.0)."""
        config = HttpClientConfig()
        assert config.http2 is True
        assert config.pool.max_connections == 100
        assert config.pool.max_keepalive_connections == 20
        assert config.pool.keepalive_expiry == pytest.approx(5.0)

    def test_ut_hc05_http2_disabled(self):
        """UT-HC05: HttpClientConfig(http2=False) → http2 is False, pool uses defaults."""
        config = HttpClientConfig(http2=False)
        assert config.http2 is False
        assert config.pool.max_connections == 100


# ==============================================================================
# UT-HC06..UT-HC07: Default values for HttpClientLoggingConfig
# ==============================================================================


class TestHttpClientLoggingConfigDefaults:
    """Test HttpClientLoggingConfig default values."""

    def test_ut_hc06_default_values(self):
        """UT-HC06: HttpClientLoggingConfig() → httpx_level='WARNING',
        httpcore_level='WARNING', trace_enabled=False."""
        logging_cfg = HttpClientLoggingConfig()
        assert logging_cfg.httpx_level == "WARNING"
        assert logging_cfg.httpcore_level == "WARNING"
        assert logging_cfg.trace_enabled is False

    def test_ut_hc07_custom_values(self):
        """UT-HC07: HttpClientLoggingConfig with custom values → matches."""
        logging_cfg = HttpClientLoggingConfig(
            httpx_level="DEBUG",
            httpcore_level="INFO",
            trace_enabled=True,
        )
        assert logging_cfg.httpx_level == "DEBUG"
        assert logging_cfg.httpcore_level == "INFO"
        assert logging_cfg.trace_enabled is True


# ==============================================================================
# UT-HC08..UT-HC10: Validation — bounds (gt=0) on HttpClientPoolConfig
# ==============================================================================


class TestHttpClientPoolConfigValidation:
    """Test HttpClientPoolConfig validation — gt=0 constraints on all fields."""

    def test_ut_hc08_max_connections_zero_rejected(self):
        """UT-HC08: HttpClientPoolConfig(max_connections=0) → ValidationError
        (gt=0 constraint violated)."""
        with pytest.raises(ValidationError) as exc_info:
            HttpClientPoolConfig(max_connections=0)

        error_message = str(exc_info.value)
        assert "max_connections" in error_message
        assert "greater than 0" in error_message

    def test_ut_hc09_max_keepalive_connections_zero_rejected(self):
        """UT-HC09: HttpClientPoolConfig(max_keepalive_connections=0) → ValidationError
        (gt=0 constraint violated)."""
        with pytest.raises(ValidationError) as exc_info:
            HttpClientPoolConfig(max_keepalive_connections=0)

        error_message = str(exc_info.value)
        assert "max_keepalive_connections" in error_message
        assert "greater than 0" in error_message

    def test_ut_hc10_keepalive_expiry_zero_rejected(self):
        """UT-HC10: HttpClientPoolConfig(keepalive_expiry=0) → ValidationError
        (gt=0 constraint violated)."""
        with pytest.raises(ValidationError) as exc_info:
            HttpClientPoolConfig(keepalive_expiry=0)

        error_message = str(exc_info.value)
        assert "keepalive_expiry" in error_message
        assert "greater than 0" in error_message

    def test_ut_hc11_max_connections_negative_rejected(self):
        """UT-HC11: HttpClientPoolConfig(max_connections=-1) → ValidationError
        (gt=0 constraint violated by negative value)."""
        with pytest.raises(ValidationError) as exc_info:
            HttpClientPoolConfig(max_connections=-1)

        error_message = str(exc_info.value)
        assert "max_connections" in error_message
        assert "greater than 0" in error_message

    def test_ut_hc12_keepalive_expiry_negative_rejected(self):
        """UT-HC12: HttpClientPoolConfig(keepalive_expiry=-0.5) → ValidationError
        (gt=0 constraint violated by negative float)."""
        with pytest.raises(ValidationError) as exc_info:
            HttpClientPoolConfig(keepalive_expiry=-0.5)

        error_message = str(exc_info.value)
        assert "keepalive_expiry" in error_message
        assert "greater than 0" in error_message


# ==============================================================================
# UT-HC13: HttpClientConfig(http2=False) via construction
# ==============================================================================


class TestHttpClientConfigHttp2Toggle:
    """Test HTTP/2 toggle on HttpClientConfig."""

    def test_ut_hc13_http2_disabled_explicitly(self):
        """UT-HC13: HttpClientConfig(http2=False) confirmed independent
        of pool config."""
        config = HttpClientConfig(
            http2=False,
            pool=HttpClientPoolConfig(max_connections=42),
        )
        assert config.http2 is False
        assert config.pool.max_connections == 42

    def test_ut_hc14_http2_enabled_explicitly(self):
        """UT-HC14: HttpClientConfig(http2=True) with custom pool → both match."""
        config = HttpClientConfig(
            http2=True,
            pool=HttpClientPoolConfig(
                max_connections=10,
                max_keepalive_connections=5,
                keepalive_expiry=1.0,
            ),
        )
        assert config.http2 is True
        assert config.pool.max_connections == 10
        assert config.pool.max_keepalive_connections == 5
        assert config.pool.keepalive_expiry == pytest.approx(1.0)


# ==============================================================================
# UT-HC15..UT-HC18: YAML loading via ConfigLoader
# ==============================================================================


class TestHttpClientConfigYamlLoading:
    """Test HTTP client config loading through ConfigLoader with YAML content."""

    def test_ut_hc15_yaml_with_custom_http_client_section(self, scenario_08):
        """UT-HC15 (Scenario #08): YAML contains
        http_client: { pool: { max_connections: 200, max_keepalive_connections: 50,
        keepalive_expiry: 30.0 } } → HttpClientPoolConfig has those values."""
        yaml_content = scenario_08
        with (
            patch("os.path.exists", return_value=True),
            patch("builtins.open", mock_open(read_data=yaml_content)),
        ):
            loader = ConfigLoader(path="dummy.yaml")
            config = loader.load()

            pool = config.http_client.pool
            assert pool.max_connections == 200
            assert pool.max_keepalive_connections == 50
            assert pool.keepalive_expiry == pytest.approx(30.0)

    def test_ut_hc16_yaml_without_http_client_section(self):
        """UT-HC16: YAML without http_client section → defaults apply
        (http2=True, pool defaults)."""
        yaml_content = """database:
  host: localhost
  password: test_password
"""
        with (
            patch("os.path.exists", return_value=True),
            patch("builtins.open", mock_open(read_data=yaml_content)),
        ):
            loader = ConfigLoader(path="dummy.yaml")
            config = loader.load()

            assert config.http_client.http2 is True
            assert config.http_client.pool.max_connections == 100
            assert config.http_client.pool.max_keepalive_connections == 20
            assert config.http_client.pool.keepalive_expiry == pytest.approx(5.0)

    def test_ut_hc17_yaml_with_http2_disabled(self, scenario_11):
        """UT-HC17 (Scenario #11): YAML contains http_client: { http2: false } →
        HttpClientConfig.http2 is False."""
        yaml_content = scenario_11
        with (
            patch("os.path.exists", return_value=True),
            patch("builtins.open", mock_open(read_data=yaml_content)),
        ):
            loader = ConfigLoader(path="dummy.yaml")
            config = loader.load()

            assert config.http_client.http2 is False

    def test_ut_hc18_yaml_with_full_logging_http_client(self):
        """UT-HC18: YAML with logging.http_client section → values loaded correctly."""
        yaml_content = """database:
  host: localhost
  password: test_password
logging:
  level: DEBUG
  http_client:
    httpx_level: DEBUG
    httpcore_level: INFO
    trace_enabled: true
"""
        with (
            patch("os.path.exists", return_value=True),
            patch("builtins.open", mock_open(read_data=yaml_content)),
        ):
            loader = ConfigLoader(path="dummy.yaml")
            config = loader.load()

            http_logging = config.logging.http_client
            assert http_logging.httpx_level == "DEBUG"
            assert http_logging.httpcore_level == "INFO"
            assert http_logging.trace_enabled is True

    def test_ut_hc19_yaml_without_logging_http_client(self):
        """UT-HC19: YAML without logging.http_client section → logging.http_client
        defaults apply (httpx_level='WARNING', httpcore_level='WARNING',
        trace_enabled=False)."""
        yaml_content = """database:
  host: localhost
  password: test_password
logging:
  level: INFO
"""
        with (
            patch("os.path.exists", return_value=True),
            patch("builtins.open", mock_open(read_data=yaml_content)),
        ):
            loader = ConfigLoader(path="dummy.yaml")
            config = loader.load()

            http_logging = config.logging.http_client
            assert http_logging.httpx_level == "WARNING"
            assert http_logging.httpcore_level == "WARNING"
            assert http_logging.trace_enabled is False


# ==============================================================================
# UT-HC20: Integration — pool limits same for Keeper and Gateway via Config
# ==============================================================================


class TestHttpClientConfigIntegration:
    """Integration-style tests verifying config accessibility for both components."""

    def test_ut_hc20_both_components_read_same_pool_config(self):
        """UT-HC20 (Scenario #09): Keeper and Gateway both read same pool config
        from shared Config object."""
        yaml_content = """database:
  host: localhost
  password: test_password
http_client:
  pool:
    max_connections: 200
    max_keepalive_connections: 50
    keepalive_expiry: 30.0
"""
        with (
            patch("os.path.exists", return_value=True),
            patch("builtins.open", mock_open(read_data=yaml_content)),
        ):
            loader = ConfigLoader(path="dummy.yaml")
            config = loader.load()

            # Both components access the same config object
            # Keeper access pattern
            keeper_http_client = config.http_client
            # Gateway access pattern
            gateway_http_client = config.http_client

            # Same object (same config instance)
            assert keeper_http_client is gateway_http_client

            # Same pool values for both
            assert keeper_http_client.pool.max_connections == 200
            assert gateway_http_client.pool.max_connections == 200
            assert keeper_http_client.pool.max_keepalive_connections == 50
            assert gateway_http_client.pool.max_keepalive_connections == 50
            assert keeper_http_client.pool.keepalive_expiry == pytest.approx(30.0)
            assert gateway_http_client.pool.keepalive_expiry == pytest.approx(30.0)

    def test_ut_hc21_root_config_has_http_client_with_defaults(self):
        """UT-HC21: Config() → config.http_client exists and has defaults."""
        config = Config()
        assert hasattr(config, "http_client")
        assert isinstance(config.http_client, HttpClientConfig)
        assert config.http_client.http2 is True
        assert isinstance(config.http_client.pool, HttpClientPoolConfig)
        assert config.http_client.pool.max_connections == 100

    def test_ut_hc22_root_config_logging_http_client_defaults(self):
        """UT-HC22: Config() → config.logging.http_client exists with defaults."""
        config = Config()
        assert hasattr(config.logging, "http_client")
        assert isinstance(config.logging.http_client, HttpClientLoggingConfig)
        assert config.logging.http_client.httpx_level == "WARNING"
        assert config.logging.http_client.httpcore_level == "WARNING"
        assert config.logging.http_client.trace_enabled is False


# ==============================================================================
# UT-HC23..UT-HC24: model_validate on HttpClientConfig
# ==============================================================================


class TestHttpClientConfigModelValidate:
    """Test HttpClientConfig.model_validate with dict input."""

    def test_ut_hc23_model_validate_with_pool_dict(self):
        """UT-HC23: model_validate with pool as dict → fields match."""
        config = HttpClientConfig.model_validate(
            {
                "http2": True,
                "pool": {
                    "max_connections": 200,
                    "max_keepalive_connections": 50,
                    "keepalive_expiry": 30.0,
                },
            }
        )
        assert config.http2 is True
        assert config.pool.max_connections == 200
        assert config.pool.max_keepalive_connections == 50
        assert config.pool.keepalive_expiry == pytest.approx(30.0)

    def test_ut_hc24_model_validate_without_pool(self):
        """UT-HC24: model_validate without pool key → pool defaults apply."""
        config = HttpClientConfig.model_validate(
            {
                "http2": False,
            }
        )
        assert config.http2 is False
        assert config.pool.max_connections == 100
        assert config.pool.max_keepalive_connections == 20
        assert config.pool.keepalive_expiry == pytest.approx(5.0)


# ==============================================================================
# Scenarios as fixtures (used by YAML tests)
# ==============================================================================


@pytest.fixture
def scenario_08() -> str:
    """Scenario #08: YAML with custom pool limits."""
    return """database:
  host: localhost
  password: test_password
http_client:
  pool:
    max_connections: 200
    max_keepalive_connections: 50
    keepalive_expiry: 30.0
"""


@pytest.fixture
def scenario_11() -> str:
    """Scenario #11: YAML with http2 disabled."""
    return """database:
  host: localhost
  password: test_password
http_client:
  http2: false
"""
