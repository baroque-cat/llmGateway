#!/usr/bin/env python3

"""
Unit tests for KeyRepository.get_keys_to_check() method.
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.core.constants import ALL_MODELS_MARKER
from src.db.database import KeyRepository


@pytest.mark.asyncio
async def test_get_keys_to_check_empty_enabled_providers():
    """
    Test that get_keys_to_check returns an empty list when enabled_provider_names is empty.
    """
    mock_pool = MagicMock()
    repo = KeyRepository(mock_pool)

    result = await repo.get_keys_to_check([])
    assert result == []


@pytest.mark.asyncio
async def test_get_keys_to_check_no_rows():
    """
    Test that get_keys_to_check returns empty list when no rows are due for check.
    """
    mock_pool = MagicMock()
    repo = KeyRepository(mock_pool)

    # Mock the database fetch to return empty list
    mock_conn = MagicMock()
    mock_conn.fetch = AsyncMock(return_value=[])
    mock_pool.acquire.return_value.__aenter__.return_value = mock_conn

    result = await repo.get_keys_to_check(["provider1"])
    assert result == []


@pytest.mark.asyncio
async def test_get_keys_to_check_normal_provider():
    """
    Test that get_keys_to_check returns correct KeyToCheck dicts for any provider.
    All providers now use ALL_MODELS_MARKER and deduplication is universal.
    """
    mock_pool = MagicMock()
    repo = KeyRepository(mock_pool)

    # Mock database rows — two different keys, both with ALL_MODELS_MARKER
    mock_rows = [
        {
            "key_id": 1,
            "key_value": "key1",
            "provider_name": "provider1",
            "model_name": ALL_MODELS_MARKER,
            "failing_since": None,
            "next_check_time": datetime(2025, 1, 1, tzinfo=UTC),
        },
        {
            "key_id": 2,
            "key_value": "key2",
            "provider_name": "provider1",
            "model_name": ALL_MODELS_MARKER,
            "failing_since": datetime(2025, 1, 1, tzinfo=UTC),
            "next_check_time": datetime(2025, 1, 2, tzinfo=UTC),
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
    assert result[0]["model_name"] == ALL_MODELS_MARKER
    assert result[0]["failing_since"] is None
    assert result[1]["key_id"] == 2
    assert result[1]["failing_since"] == datetime(2025, 1, 1, tzinfo=UTC)


@pytest.mark.asyncio
async def test_get_keys_to_check_deduplicates_all_providers():
    """
    Test that get_keys_to_check deduplicates by key_id for all providers.
    Multiple model rows for the same key are collapsed to one entry.
    """
    mock_pool = MagicMock()
    repo = KeyRepository(mock_pool)

    # Multiple rows for the same key_id (could happen from legacy per-model rows
    # or from JOIN producing multiple matches)
    mock_rows = [
        {
            "key_id": 1,
            "key_value": "key1",
            "provider_name": "provider1",
            "model_name": ALL_MODELS_MARKER,
            "failing_since": None,
            "next_check_time": datetime(2025, 1, 1, tzinfo=UTC),
        },
        {
            "key_id": 1,
            "key_value": "key1",
            "provider_name": "provider1",
            "model_name": "gpt-4",
            "failing_since": None,
            "next_check_time": datetime(2025, 1, 1, tzinfo=UTC),
        },
        {
            "key_id": 2,
            "key_value": "key2",
            "provider_name": "provider1",
            "model_name": ALL_MODELS_MARKER,
            "failing_since": None,
            "next_check_time": datetime(2025, 1, 2, tzinfo=UTC),
        },
    ]
    mock_conn = MagicMock()
    mock_conn.fetch = AsyncMock(return_value=mock_rows)
    mock_pool.acquire.return_value.__aenter__.return_value = mock_conn

    result = await repo.get_keys_to_check(["provider1"])

    # Should deduplicate by key_id — only one entry per key
    assert len(result) == 2
    key_ids = [item["key_id"] for item in result]
    assert set(key_ids) == {1, 2}


@pytest.mark.asyncio
async def test_get_keys_to_check_prefers_all_models_marker():
    """
    Test that get_keys_to_check prefers ALL_MODELS_MARKER rows during deduplication
    because the query orders by ``s.model_name = '__ALL_MODELS__' DESC``.
    """
    mock_pool = MagicMock()
    repo = KeyRepository(mock_pool)

    # The query ORDER BY places ALL_MODELS_MARKER rows first.
    # key_id=1 has both a per-model row and an ALL_MODELS_MARKER row.
    # The ALL_MODELS_MARKER row appears first and is kept during dedup.
    mock_rows = [
        {
            "key_id": 1,
            "key_value": "key1",
            "provider_name": "provider1",
            "model_name": ALL_MODELS_MARKER,
            "failing_since": None,
            "next_check_time": datetime(2025, 1, 1, tzinfo=UTC),
        },
        {
            "key_id": 1,
            "key_value": "key1",
            "provider_name": "provider1",
            "model_name": "claude-sonnet",
            "failing_since": None,
            "next_check_time": datetime(2025, 1, 1, tzinfo=UTC),
        },
    ]
    mock_conn = MagicMock()
    mock_conn.fetch = AsyncMock(return_value=mock_rows)
    mock_pool.acquire.return_value.__aenter__.return_value = mock_conn

    result = await repo.get_keys_to_check(["provider1"])

    # Only one entry after dedup, and it should be the ALL_MODELS_MARKER one
    assert len(result) == 1
    assert result[0]["key_id"] == 1
    assert result[0]["model_name"] == ALL_MODELS_MARKER
