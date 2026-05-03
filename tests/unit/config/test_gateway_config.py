#!/usr/bin/env python3

"""
Unit tests for GatewayConfig schema and its integration with Config.

Tests cover: defaults, custom values, partial overrides, validation errors,
root Config integration, and YAML loading via ConfigLoader.
"""

import os
from unittest.mock import mock_open, patch

import pytest
from pydantic import ValidationError

from src.config.loader import ConfigLoader
from src.config.schemas import Config, GatewayConfig

# Minimal env vars required after defaults.py now uses ${VAR} references
_BASE_ENV: dict[str, str] = {
    "DB_HOST": "localhost",
    "DB_PORT": "5432",
    "DB_USER": "test_user",
    "DB_PASSWORD": "test_password",
    "DB_NAME": "test_db",
    "GATEWAY_HOST": "0.0.0.0",
    "GATEWAY_PORT": "55300",
    "GATEWAY_WORKERS": "4",
}


class TestGatewayConfigDefaults:
    """Test GatewayConfig default field values."""

    def test_default_values(self):
        """UT-G01: GatewayConfig() creates with host='0.0.0.0', port=55300, workers=4."""
        config = GatewayConfig()
        assert config.host == "0.0.0.0"
        assert config.port == 55300
        assert config.workers == 4


class TestGatewayConfigCustomValues:
    """Test GatewayConfig with explicitly provided values."""

    def test_custom_values(self):
        """UT-G02: GatewayConfig(host='127.0.0.1', port=9090, workers=2) → values match."""
        config = GatewayConfig(host="127.0.0.1", port=9090, workers=2)
        assert config.host == "127.0.0.1"
        assert config.port == 9090
        assert config.workers == 2

    def test_partial_override_port_only(self):
        """UT-G03: GatewayConfig(port=8080) → port=8080, host='0.0.0.0', workers=4."""
        config = GatewayConfig(port=8080)
        assert config.port == 8080
        assert config.host == "0.0.0.0"
        assert config.workers == 4


class TestGatewayConfigValidation:
    """Test GatewayConfig validation constraints on port and workers."""

    def test_port_zero_raises(self):
        """UT-G04 / SEC-02: GatewayConfig(port=0) → ValidationError with gt=0."""
        with pytest.raises(ValidationError) as exc_info:
            GatewayConfig(port=0)
        errors = exc_info.value.errors()
        assert any(
            "gt" in str(e.get("ctx", {})) or "greater than 0" in str(e) for e in errors
        )

    def test_port_above_max_raises(self):
        """UT-G05 / SEC-02: GatewayConfig(port=99999) → ValidationError with lt=65536."""
        with pytest.raises(ValidationError) as exc_info:
            GatewayConfig(port=99999)
        errors = exc_info.value.errors()
        assert any(
            "lt" in str(e.get("ctx", {})) or "less than 65536" in str(e) for e in errors
        )

    def test_port_exactly_65536_raises(self):
        """SEC-02: GatewayConfig(port=65536) → ValidationError (lt=65536 means <65536)."""
        with pytest.raises(ValidationError) as exc_info:
            GatewayConfig(port=65536)
        errors = exc_info.value.errors()
        assert any(
            "lt" in str(e.get("ctx", {})) or "less than 65536" in str(e) for e in errors
        )

    def test_workers_zero_raises(self):
        """UT-G06 / SEC-01: GatewayConfig(workers=0) → ValidationError with gt=0."""
        with pytest.raises(ValidationError) as exc_info:
            GatewayConfig(workers=0)
        errors = exc_info.value.errors()
        assert any(
            "gt" in str(e.get("ctx", {})) or "greater than 0" in str(e) for e in errors
        )

    def test_workers_above_max_raises(self):
        """UT-G07 / SEC-01: GatewayConfig(workers=65) → ValidationError with le=64."""
        with pytest.raises(ValidationError) as exc_info:
            GatewayConfig(workers=65)
        errors = exc_info.value.errors()
        assert any(
            "le" in str(e.get("ctx", {})) or "less than or equal to 64" in str(e)
            for e in errors
        )

    def test_workers_exactly_64_is_valid(self):
        """SEC-01 boundary: GatewayConfig(workers=64) is valid (le=64 means ≤64)."""
        config = GatewayConfig(workers=64)
        assert config.workers == 64

    def test_port_65535_is_valid(self):
        """SEC-02 boundary: GatewayConfig(port=65535) is valid (lt=65536 means <65536)."""
        config = GatewayConfig(port=65535)
        assert config.port == 65535


class TestGatewayConfigInRootConfig:
    """Test GatewayConfig as a field of the root Config model."""

    def test_config_contains_gateway_field(self):
        """UT-G08 part 1: Config() contains field `gateway` of type GatewayConfig with defaults."""
        config = Config()
        assert hasattr(config, "gateway")
        assert isinstance(config.gateway, GatewayConfig)
        assert config.gateway.host == "0.0.0.0"
        assert config.gateway.port == 55300
        assert config.gateway.workers == 4

    def test_config_model_validate_with_gateway(self):
        """UT-G08 part 2: Config.model_validate with gateway dict → values match."""
        config = Config.model_validate(
            {"gateway": {"host": "127.0.0.1", "port": 9090, "workers": 2}}
        )
        assert config.gateway.host == "127.0.0.1"
        assert config.gateway.port == 9090
        assert config.gateway.workers == 2

    def test_config_extra_fields_forbidden_at_root(self):
        """SEC-06: Config.model_validate with unknown field at root level → ValidationError (extra='forbid')."""
        with pytest.raises(ValidationError) as exc_info:
            Config.model_validate({"unknown_field": "value"})
        errors = exc_info.value.errors()
        assert any(
            e.get("type") == "extra_forbidden" or "extra" in str(e.get("type", ""))
            for e in errors
        )

    def test_config_nested_extra_fields_forbidden_in_gateway(self):
        """SEC-06: Config.model_validate with unknown field inside gateway dict → ValidationError
        (GatewayConfig now has extra='forbid', matching root Config's strictness)."""
        with pytest.raises(ValidationError) as exc_info:
            Config.model_validate({"gateway": {"unknown_field": "value"}})
        errors = exc_info.value.errors()
        assert any(
            e.get("type") == "extra_forbidden" or "extra" in str(e.get("type", ""))
            for e in errors
        )


class TestGatewayConfigYamlLoading:
    """Test GatewayConfig loading via ConfigLoader from YAML."""

    def test_yaml_without_gateway_section(self):
        """UT-G09: YAML without gateway section → config.gateway uses env-resolved defaults."""
        yaml_content = """providers: {}
logging: {}
"""
        with (
            patch.dict(os.environ, _BASE_ENV),
            patch("os.path.exists", return_value=True),
            patch("builtins.open", mock_open(read_data=yaml_content)),
        ):
            loader = ConfigLoader(path="dummy.yaml")
            config = loader.load()

            assert config.gateway.host == "0.0.0.0"
            assert config.gateway.port == 55300
            assert config.gateway.workers == 4

    def test_yaml_with_gateway_section(self):
        """UT-G10: YAML with gateway section → values match."""
        yaml_content = """providers: {}
logging: {}
gateway:
  host: "127.0.0.1"
  port: 9090
  workers: 2
"""
        with (
            patch.dict(os.environ, _BASE_ENV),
            patch("os.path.exists", return_value=True),
            patch("builtins.open", mock_open(read_data=yaml_content)),
        ):
            loader = ConfigLoader(path="dummy.yaml")
            config = loader.load()

            assert config.gateway.host == "127.0.0.1"
            assert config.gateway.port == 9090
            assert config.gateway.workers == 2
