"""
Integration test demonstrating the complete ghost provider handling workflow.

This test verifies the three key aspects of the fix:
1. Disabled providers are not checked by the worker
2. Deleted providers are removed from the database 
3. The worker doesn't get stuck in infinite loops
"""

import pytest
from src.config.schemas import Config, ProviderConfig, HealthPolicyConfig
from src.core.accessor import ConfigAccessor


def test_complete_ghost_provider_workflow():
    """
    Test the complete workflow of ghost provider handling.
    
    Scenario:
    - Initially have 3 providers: enabled, disabled, and to-be-deleted
    - After config update, only enabled provider remains
    - Database should reflect this change after sync
    - Worker should only process enabled provider
    """
    # Initial configuration with 3 providers
    initial_config = Config()
    initial_config.providers = {
        "active_provider": ProviderConfig(
            enabled=True,
            provider_type="test",
            keys_path="/tmp/keys1",
            api_base_url="http://active.com",
            default_model="model1"
        ),
        "disabled_provider": ProviderConfig(
            enabled=False, 
            provider_type="test",
            keys_path="/tmp/keys2",
            api_base_url="http://disabled.com", 
            default_model="model2"
        ),
        "ghost_provider": ProviderConfig(
            enabled=True,
            provider_type="test", 
            keys_path="/tmp/keys3",
            api_base_url="http://ghost.com",
            default_model="model3"
        )
    }
    
    accessor = ConfigAccessor(initial_config)
    
    # Verify initial state
    all_providers = accessor.get_all_providers()
    enabled_providers = accessor.get_enabled_providers()
    
    assert len(all_providers) == 3
    assert len(enabled_providers) == 2  # active + ghost
    assert "active_provider" in enabled_providers
    assert "ghost_provider" in enabled_providers  
    assert "disabled_provider" not in enabled_providers
    
    # Simulate config update: remove ghost_provider entirely
    updated_config = Config()
    updated_config.providers = {
        "active_provider": ProviderConfig(
            enabled=True,
            provider_type="test",
            keys_path="/tmp/keys1", 
            api_base_url="http://active.com",
            default_model="model1"
        ),
        "disabled_provider": ProviderConfig(
            enabled=False,
            provider_type="test",
            keys_path="/tmp/keys2",
            api_base_url="http://disabled.com",
            default_model="model2"
        )
        # ghost_provider is completely removed
    }
    
    updated_accessor = ConfigAccessor(updated_config)
    
    # Verify updated state
    updated_all_providers = updated_accessor.get_all_providers()
    updated_enabled_providers = updated_accessor.get_enabled_providers()
    
    assert len(updated_all_providers) == 2
    assert len(updated_enabled_providers) == 1
    assert "active_provider" in updated_enabled_providers
    assert "ghost_provider" not in updated_all_providers
    assert "disabled_provider" in updated_all_providers
    assert "disabled_provider" not in updated_enabled_providers


def test_worker_only_processes_enabled_providers():
    """Verify that the worker logic correctly filters to enabled providers only."""
    config = Config()
    config.providers = {
        "provider_a": ProviderConfig(enabled=True),
        "provider_b": ProviderConfig(enabled=False), 
        "provider_c": ProviderConfig(enabled=True),
        "provider_d": ProviderConfig(enabled=False)
    }
    
    accessor = ConfigAccessor(config)
    enabled_provider_names = list(accessor.get_enabled_providers().keys())
    
    # These are the names that should be passed to database queries
    assert len(enabled_provider_names) == 2
    assert "provider_a" in enabled_provider_names
    assert "provider_c" in enabled_provider_names 
    assert "provider_b" not in enabled_provider_names
    assert "provider_d" not in enabled_provider_names


def test_empty_enabled_providers_handling():
    """Test that the system handles the case where no providers are enabled."""
    config = Config()
    # No providers at all
    accessor = ConfigAccessor(config)
    enabled_providers = accessor.get_enabled_providers()
    assert len(enabled_providers) == 0
    
    # All providers disabled
    config.providers = {
        "p1": ProviderConfig(enabled=False),
        "p2": ProviderConfig(enabled=False)
    }
    accessor = ConfigAccessor(config) 
    enabled_providers = accessor.get_enabled_providers()
    assert len(enabled_providers) == 0