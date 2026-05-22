#!/usr/bin/env python3

"""
Unit tests for KeyRepository.get_status_summary() method.

Tests the aggregation query that provides data for Prometheus metrics.
The query no longer includes model_name in SELECT or GROUP BY.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.db.database import KeyRepository, StatusSummaryItem


@pytest.mark.asyncio
async def test_get_status_summary_empty_database():
    """Test get_status_summary returns empty list when database has no key statuses."""
    mock_pool = MagicMock()
    repo = KeyRepository(mock_pool)

    # Mock empty result
    mock_conn = MagicMock()
    mock_conn.fetch = AsyncMock(return_value=[])
    mock_pool.acquire.return_value.__aenter__.return_value = mock_conn

    result = await repo.get_status_summary()

    assert result == []
    # Verify key fragments of the SQL query
    query = mock_conn.fetch.call_args[0][0]
    assert "key_model_status" in query
    assert "GROUP BY" in query
    assert "p.name" in query
    # s.model_name should NOT appear (removed from query)
    assert "s.model_name" not in query
    assert "s.status" in query


@pytest.mark.asyncio
async def test_get_status_summary_with_data():
    """Test get_status_summary returns correctly formatted StatusSummaryItems
    without the model field."""
    mock_pool = MagicMock()
    repo = KeyRepository(mock_pool)

    # Mock database rows — no model column
    mock_rows = [
        {"provider": "openai", "status": "valid", "count": 5},
        {"provider": "openai", "status": "invalid", "count": 2},
        {"provider": "anthropic", "status": "valid", "count": 3},
        {"provider": "anthropic", "status": "untested", "count": 1},
    ]
    mock_conn = MagicMock()
    mock_conn.fetch = AsyncMock(return_value=mock_rows)
    mock_pool.acquire.return_value.__aenter__.return_value = mock_conn

    result = await repo.get_status_summary()

    assert len(result) == 4
    # Verify structure matches StatusSummaryItem TypedDict (provider, status, count only)
    for i, item in enumerate(result):
        assert "provider" in item
        assert "status" in item
        assert "count" in item
        assert "model" not in item
        assert item["provider"] == mock_rows[i]["provider"]
        assert item["status"] == mock_rows[i]["status"]
        assert item["count"] == mock_rows[i]["count"]


@pytest.mark.asyncio
async def test_get_status_summary_query_includes_all_statuses():
    """Test get_status_summary includes all status values (valid, invalid, untested, etc.)."""
    mock_pool = MagicMock()
    repo = KeyRepository(mock_pool)

    # Mock database rows with various statuses (no model field)
    mock_rows = [
        {"provider": "test", "status": "valid", "count": 5},
        {"provider": "test", "status": "invalid", "count": 2},
        {"provider": "test", "status": "untested", "count": 3},
        {"provider": "test", "status": "rate_limited", "count": 1},
        {"provider": "test", "status": "quota_exceeded", "count": 1},
    ]
    mock_conn = MagicMock()
    mock_conn.fetch = AsyncMock(return_value=mock_rows)
    mock_pool.acquire.return_value.__aenter__.return_value = mock_conn

    result = await repo.get_status_summary()

    # All statuses should be present
    statuses = {item["status"] for item in result}
    assert "valid" in statuses
    assert "invalid" in statuses
    assert "untested" in statuses
    assert "rate_limited" in statuses
    assert "quota_exceeded" in statuses


@pytest.mark.asyncio
async def test_get_status_summary_database_error():
    """Test get_status_summary propagates database errors."""
    mock_pool = MagicMock()
    repo = KeyRepository(mock_pool)

    # Mock database error
    mock_conn = MagicMock()
    mock_conn.fetch = AsyncMock(side_effect=Exception("Database connection failed"))
    mock_pool.acquire.return_value.__aenter__.return_value = mock_conn

    with pytest.raises(Exception, match="Database connection failed"):
        await repo.get_status_summary()


def test_status_summary_item_no_model_field():
    """StatusSummaryItem TypedDict definition excludes model."""
    # The TypedDict's required keys and optional keys together define all valid keys
    all_keys = set(StatusSummaryItem.__required_keys__) | set(
        StatusSummaryItem.__optional_keys__
    )

    assert "provider" in all_keys
    assert "status" in all_keys
    assert "count" in all_keys
    assert "model" not in all_keys


@pytest.mark.asyncio
async def test_get_status_summary_no_model_group_by():
    """SQL query excludes model dimension from GROUP BY."""
    mock_pool = MagicMock()
    repo = KeyRepository(mock_pool)

    mock_conn = MagicMock()
    mock_conn.fetch = AsyncMock(return_value=[])
    mock_pool.acquire.return_value.__aenter__.return_value = mock_conn

    await repo.get_status_summary()

    query = mock_conn.fetch.call_args[0][0]
    assert "key_model_status" in query
    assert "GROUP BY p.name, s.status" in query
    # model should NOT appear in GROUP BY
    assert "model_name" not in query
