#!/usr/bin/env python3

"""
Unit tests for KeyRepository.get_keys_to_check() method.
"""

from datetime import datetime, UTC
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.db.database import KeyRepository


@pytest.mark.asyncio
async def test_get_keys_to_check_empty_enabled_providers():
    """
    Test that get_keys_to_check returns an empty list when enabled_provider_names is empty.
    """
    mock_pool = MagicMock()
    mock_accessor = MagicMock()
    repo = KeyRepository(mock_pool, mock_accessor)

    result = await repo.get_keys_to_check([])
    assert result == []


@pytest.mark.asyncio
async def test_get_keys_to_check_no_rows():
    """
    Test that get_keys_to_check returns empty list when no rows are due for check.
    """
    mock_pool = MagicMock()
    mock_accessor = MagicMock()
    repo = KeyRepository(mock_pool, mock_accessor)

    # Mock the database fetch to return empty list
    mock_conn = MagicMock()
    mock_conn.fetch = AsyncMock(return_value=[])
    mock_pool.acquire.return_value.__aenter__.return_value = mock_conn

    result = await repo.get_keys_to_check(["provider1"])
    assert result == []


@pytest.mark.asyncio
async def test_get_keys_to_check_normal_provider():
    """
    Test that get_keys_to_check returns correct KeyToCheck dicts for normal providers.
    """
    mock_pool = MagicMock()
    mock_accessor = MagicMock()
    repo = KeyRepository(mock_pool, mock_accessor)

    # Mock provider config with shared_key_status=False (default)
    mock_provider_config = MagicMock()
    mock_provider_config.shared_key_status = False
    mock_accessor.get_provider.return_value = mock_provider_config

    # Mock database rows
    mock_rows = [
        {
            "key_id": 1,
            "key_value": "key1",
            "provider_name": "provider1",
            "model_name": "model1",
            "failing_since": None,
        },
        {
            "key_id": 2,
            "key_value": "key2",
            "provider_name": "provider1",
            "model_name": "model2",
            "failing_since": datetime(2025, 1, 1, tzinfo=UTC),
        },
    ]
    mock_conn = MagicMock()
    mock_conn.fetch = AsyncMock(return_value=mock_rows)
    mock_pool.acquire.return_value.__aenter__.return_value = mock_conn

    result = await repo.get_keys_to_check(["provider1"])

    assert len(result) == 2
    assert result[0]["key_id"] == 1
    assert result[0]["key_value"] == "key1"
    assert result[0]["provider_name"] == "provider1"
    assert result[0]["model_name"] == "model1"
    assert result[0]["failing_since"] is None
    assert result[1]["key_id"] == 2
    assert result[1]["failing_since"] == datetime(2025, 1, 1, tzinfo=UTC)


@pytest.mark.asyncio
async def test_get_keys_to_check_shared_key_status():
    """
    Test that get_keys_to_check handles shared_key_status providers correctly,
    deduplicating keys and using ALL_MODELS_MARKER.
    """
    mock_pool = MagicMock()
    mock_accessor = MagicMock()
    repo = KeyRepository(mock_pool, mock_accessor)

    # Mock provider config with shared_key_status=True
    mock_provider_config = MagicMock()
    mock_provider_config.shared_key_status = True
    mock_accessor.get_provider.return_value = mock_provider_config

    # Mock database rows with multiple entries for same key (different models)
    # For shared_key_status, rows should have model_name = "__ALL_MODELS__"
    mock_rows = [
        {
            "key_id": 1,
            "key_value": "key1",
            "provider_name": "shared_provider",
            "model_name": "__ALL_MODELS__",
            "failing_since": None,
        },
        {
            "key_id": 1,
            "key_value": "key1",
            "provider_name": "shared_provider",
            "model_name": "__ALL_MODELS__",
            "failing_since": None,
        },  # duplicate due to join? should be deduplicated
        {
            "key_id": 2,
            "key_value": "key2",
            "provider_name": "shared_provider",
            "model_name": "__ALL_MODELS__",
            "failing_since": None,
        },
    ]
    mock_conn = MagicMock()
    mock_conn.fetch = AsyncMock(return_value=mock_rows)
    mock_pool.acquire.return_value.__aenter__.return_value = mock_conn

    result = await repo.get_keys_to_check(["shared_provider"])

    # Should deduplicate by key_id, only one entry per key
    assert len(result) == 2
    key_ids = [item["key_id"] for item in result]
    assert set(key_ids) == {1, 2}
    # model_name should be "__ALL_MODELS__"
    assert result[0]["model_name"] == "__ALL_MODELS__"
    assert result[1]["model_name"] == "__ALL_MODELS__"


@pytest.mark.asyncio
async def test_get_keys_to_check_mixed_providers():
    """
    Test that get_keys_to_check correctly handles a mix of shared and normal providers.
    """
    mock_pool = MagicMock()
    mock_accessor = MagicMock()
    repo = KeyRepository(mock_pool, mock_accessor)

    # Configure accessor to return different configs based on provider name
    def get_provider_side_effect(provider_name: str):
        mock_config = MagicMock()
        if provider_name == "shared_provider":
            mock_config.shared_key_status = True
        else:
            mock_config.shared_key_status = False
        return mock_config

    mock_accessor.get_provider.side_effect = get_provider_side_effect

    # Mock database rows
    mock_rows = [
        # Shared provider
        {
            "key_id": 1,
            "key_value": "key1",
            "provider_name": "shared_provider",
            "model_name": "__ALL_MODELS__",
            "failing_since": None,
        },
        # Normal provider
        {
            "key_id": 2,
            "key_value": "key2",
            "provider_name": "normal_provider",
            "model_name": "model1",
            "failing_since": None,
        },
        {
            "key_id": 3,
            "key_value": "key3",
            "provider_name": "normal_provider",
            "model_name": "model2",
            "failing_since": None,
        },
    ]
    mock_conn = MagicMock()
    mock_conn.fetch = AsyncMock(return_value=mock_rows)
    mock_pool.acquire.return_value.__aenter__.return_value = mock_conn

    result = await repo.get_keys_to_check(["shared_provider", "normal_provider"])

    # Should have 3 entries: 1 for shared provider (deduplicated), 2 for normal provider
    assert len(result) == 3
    # Check that shared provider entry has __ALL_MODELS__
    shared_entries = [r for r in result if r["provider_name"] == "shared_provider"]
    assert len(shared_entries) == 1
    assert shared_entries[0]["model_name"] == "__ALL_MODELS__"
    # Normal provider entries keep their model names
    normal_entries = [r for r in result if r["provider_name"] == "normal_provider"]
    assert len(normal_entries) == 2
    assert {e["model_name"] for e in normal_entries} == {"model1", "model2"}
