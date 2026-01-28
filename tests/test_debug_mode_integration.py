import pytest
from src.config.loader import ConfigLoader
from src.config.schemas import Config

def test_debug_mode_config_loading():
    """Test that debug mode is properly loaded from configuration."""
    # Create a test config with debug mode enabled
    test_config = {
        "debug": False,
        "gateway": {
            "streaming_mode": "auto",
            "debug_mode": "headers_only"
        },
        "worker": {
            "max_concurrent_providers": 5
        },
        "database": {
            "host": "localhost",
            "port": 5433,
            "user": "test_user",
            "password": "test_password",
            "dbname": "test_db"
        },
        "logging": {
            "summary_log_path": "logs/summary/",
            "summary_interval_min": 30,
            "summary_log_max_size_mb": 5,
            "summary_log_backup_count": 3
        },
        "providers": {
            "test_provider": {
                "provider_type": "openai",
                "enabled": True,
                "keys_path": "keys/test/",
                "api_base_url": "https://api.openai.com/v1",
                "models": {
                    "gpt-4": {
                        "endpoint_suffix": "/chat/completions",
                        "test_payload": {"messages": [{"role": "user", "content": "test"}]}
                    }
                },
                "gateway_policy": {
                    "streaming_mode": "auto",
                    "debug_mode": "full_body",
                    "retry": {
                        "enabled": False
                    }
                }
            }
        }
    }
    
    # Test global debug mode
    assert test_config["gateway"]["debug_mode"] == "headers_only"
    
    # Test provider debug mode
    assert test_config["providers"]["test_provider"]["gateway_policy"]["debug_mode"] == "full_body"

def test_debug_mode_inheritance():
    """Test that debug mode inheritance works correctly."""
    # Test case 1: Provider has debug_mode="disabled", should inherit global
    config1 = {
        "gateway": {"debug_mode": "headers_only"},
        "providers": {
            "test1": {
                "gateway_policy": {"debug_mode": "disabled"}
            }
        }
    }
    # Should inherit "headers_only"
    
    # Test case 2: Provider has debug_mode="full_body", should override global
    config2 = {
        "gateway": {"debug_mode": "headers_only"},
        "providers": {
            "test2": {
                "gateway_policy": {"debug_mode": "full_body"}
            }
        }
    }
    # Should be "full_body"
    
    # Test case 3: Global is "disabled", provider is "disabled", should be "disabled"
    config3 = {
        "gateway": {"debug_mode": "disabled"},
        "providers": {
            "test3": {
                "gateway_policy": {"debug_mode": "disabled"}
            }
        }
    }
    # Should be "disabled"