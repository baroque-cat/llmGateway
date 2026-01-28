import pytest
from src.config.schemas import Config, GatewayGlobalConfig, GatewayPolicyConfig

def test_gateway_global_config_debug_mode():
    """Test that GatewayGlobalConfig has debug_mode field."""
    config = GatewayGlobalConfig()
    assert hasattr(config, 'debug_mode')
    assert config.debug_mode == "disabled"

def test_gateway_policy_config_debug_mode():
    """Test that GatewayPolicyConfig has debug_mode field."""
    config = GatewayPolicyConfig()
    assert hasattr(config, 'debug_mode')
    assert config.debug_mode == "disabled"

def test_config_has_gateway_debug_mode():
    """Test that main Config has gateway with debug_mode."""
    config = Config()
    assert hasattr(config.gateway, 'debug_mode')
    assert config.gateway.debug_mode == "disabled"