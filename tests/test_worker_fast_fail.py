#!/usr/bin/env python3

"""
Test suite for the worker fast fail functionality.
These tests ensure that the fast_status_mapping in worker_health_policy
works correctly for health checks.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock
from src.config.schemas import ProviderConfig, HealthPolicyConfig
from src.core.enums import ErrorReason
from src.core.models import CheckResult
from src.providers.impl.openai_like import OpenAILikeProvider
import httpx


@pytest.fixture
def mock_client():
    client = AsyncMock(spec=httpx.AsyncClient)
    client.post = AsyncMock()
    return client


@pytest.mark.asyncio
async def test_worker_fast_fail_configuration_validation():
    """
    Test that the fast_status_mapping field is properly validated in HealthPolicyConfig.
    """
    # Valid configuration should pass validation
    config = ProviderConfig(
        provider_type="test",
        worker_health_policy=HealthPolicyConfig(
            fast_status_mapping={418: "no_quota"}
        )
    )
    
    # This should not raise any validation errors when loaded through the full pipeline
    # We'll test this indirectly through the validator in other test files
    
    # Test that invalid ErrorReason values are caught
    from src.config.validator import ConfigValidator
    validator = ConfigValidator()
    
    # Create a minimal config with invalid mapping
    from src.config.schemas import Config, DatabaseConfig
    bad_config = Config(
        database=DatabaseConfig(password="test"),
        providers={
            "test_provider": ProviderConfig(
                provider_type="test",
                worker_health_policy=HealthPolicyConfig(
                    fast_status_mapping={418: "invalid_reason"}
                )
            )
        }
    )
    
    with pytest.raises(ValueError) as exc_info:
        validator.validate(bad_config)
    
    assert "is not a valid ErrorReason" in str(exc_info.value)


@pytest.mark.asyncio
async def test_worker_fast_fail_integration(mock_client):
    """
    Test that the worker fast fail works correctly with a mock provider.
    """
    config = ProviderConfig(
        provider_type="openai",
        worker_health_policy=HealthPolicyConfig(
            fast_status_mapping={418: "no_quota"}
        ),
        models={"test-model": MagicMock()}
    )
    
    provider = OpenAILikeProvider("test", config)
    
    # Mock a 418 response
    mock_response = AsyncMock(spec=httpx.Response)
    mock_response.status_code = 418
    mock_response.text = "I'm a teapot"
    mock_response.elapsed.total_seconds.return_value = 0.1
    
    # Mock the HTTPStatusError exception
    mock_exception = httpx.HTTPStatusError(
        "Request failed", 
        request=MagicMock(), 
        response=mock_response
    )
    
    mock_client.post.side_effect = mock_exception
    
    # Call the check method
    result = await provider.check(mock_client, "test-token", model="test-model")
    
    # Verify that fast fail was triggered
    assert result.error_reason == ErrorReason.NO_QUOTA
    assert "Worker fast fail" in result.message
    assert result.status_code == 418


@pytest.mark.asyncio
async def test_worker_fast_fail_no_mapping(mock_client):
    """
    Test that normal error handling works when no fast fail mapping exists.
    """
    config = ProviderConfig(
        provider_type="openai",
        worker_health_policy=HealthPolicyConfig(
            fast_status_mapping={}  # Empty mapping
        ),
        models={"test-model": MagicMock()}
    )
    
    provider = OpenAILikeProvider("test", config)
    
    # Mock a 401 response (should map to INVALID_KEY normally)
    mock_response = AsyncMock(spec=httpx.Response)
    mock_response.status_code = 401
    mock_response.text = "Unauthorized"
    mock_response.elapsed.total_seconds.return_value = 0.1
    
    mock_exception = httpx.HTTPStatusError(
        "Request failed", 
        request=MagicMock(), 
        response=mock_response
    )
    
    mock_client.post.side_effect = mock_exception
    
    result = await provider.check(mock_client, "test-token", model="test-model")
    
    # Should use normal mapping, not fast fail
    assert result.error_reason == ErrorReason.INVALID_KEY
    assert "Worker fast fail" not in result.message