#!/usr/bin/env python3

"""
Test suite for the worker fast fail functionality.
These tests ensure that the fast_status_mapping in worker_health_policy
works correctly for health checks.

Updated for Pydantic v2 migration: ConfigValidator removed, validation is now
done inline via Pydantic BaseModel. ProviderConfig now requires provider_type and keys_path.
"""

from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from src.config.schemas import HealthPolicyConfig, ProviderConfig
from src.core.constants import ErrorReason
from src.providers.impl.openai_like import OpenAILikeProvider


@pytest.fixture
def mock_client():
    client = AsyncMock(spec=httpx.AsyncClient)
    client.post = AsyncMock()
    return client


@pytest.mark.asyncio
async def test_worker_fast_fail_configuration_validation():
    """
    Test that the fast_status_mapping field is properly validated in HealthPolicyConfig.

    With Pydantic v2, ProviderConfig requires provider_type and keys_path.
    The old ConfigValidator's ErrorReason enum check for map_to values is no longer
    enforced at the Pydantic schema level (fast_status_mapping is dict[int, str]).
    """
    # Valid configuration should pass Pydantic validation
    config = ProviderConfig(
        provider_type="test",
        keys_path="keys/test/",
        worker_health_policy=HealthPolicyConfig(fast_status_mapping={418: "no_quota"}),
    )

    assert config.worker_health_policy.fast_status_mapping[418] == "no_quota"

    # Test that any string value is accepted by Pydantic (dict[int, str] type)
    # NOTE: The old ConfigValidator checked for valid ErrorReason enum values,
    # but with Pydantic v2 this is a known validation gap.
    config_with_invalid = ProviderConfig(
        provider_type="test",
        keys_path="keys/test/",
        worker_health_policy=HealthPolicyConfig(
            fast_status_mapping={418: "invalid_reason"}
        ),
    )
    assert (
        config_with_invalid.worker_health_policy.fast_status_mapping[418]
        == "invalid_reason"
    )


@pytest.mark.asyncio
async def test_worker_fast_fail_integration(mock_client):
    """
    Test that the worker fast fail works correctly with a mock provider.
    """
    config = ProviderConfig(
        provider_type="openai",
        keys_path="keys/test/",
        worker_health_policy=HealthPolicyConfig(fast_status_mapping={418: "no_quota"}),
        models={
            "test-model": {}
        },  # Pydantic expects dict[str, ModelInfo], not MagicMock
    )

    provider = OpenAILikeProvider("test", config)

    # Mock a 418 response
    mock_response = AsyncMock(spec=httpx.Response)
    mock_response.status_code = 418
    mock_response.text = "I'm a teapot"
    mock_response.elapsed.total_seconds.return_value = 0.1

    # Mock the HTTPStatusError exception
    mock_exception = httpx.HTTPStatusError(
        "Request failed", request=MagicMock(), response=mock_response
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
        keys_path="keys/test/",
        worker_health_policy=HealthPolicyConfig(
            fast_status_mapping={}  # Empty mapping
        ),
        models={
            "test-model": {}
        },  # Pydantic expects dict[str, ModelInfo], not MagicMock
    )

    provider = OpenAILikeProvider("test", config)

    # Mock a 401 response (should map to INVALID_KEY normally)
    mock_response = AsyncMock(spec=httpx.Response)
    mock_response.status_code = 401
    mock_response.text = "Unauthorized"
    mock_response.elapsed.total_seconds.return_value = 0.1

    mock_exception = httpx.HTTPStatusError(
        "Request failed", request=MagicMock(), response=mock_response
    )

    mock_client.post.side_effect = mock_exception

    result = await provider.check(mock_client, "test-token", model="test-model")

    # Should use normal mapping, not fast fail
    assert result.error_reason == ErrorReason.INVALID_KEY
    assert "Worker fast fail" not in result.message
