#!/usr/bin/env python3

"""
Unit tests for KeyRepository.get_status_summary() method.

Tests the aggregation query that provides data for Prometheus metrics.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.db.database import KeyRepository


@pytest.mark.asyncio
async def test_get_status_summary_empty_database():
    """Test get_status_summary returns empty list when database has no key statuses."""
    mock_pool = MagicMock()
    mock_accessor = MagicMock()
    repo = KeyRepository(mock_pool, mock_accessor)

    # Mock empty result
    mock_conn = MagicMock()
    mock_conn.fetch = AsyncMock(return_value=[])
    mock_pool.acquire.return_value.__aenter__.return_value = mock_conn

    result = await repo.get_status_summary()

    assert result == []
    mock_conn.fetch.assert_called_once_with("""
            SELECT
                p.name AS provider,
                s.model_name AS model,
                s.status,
                COUNT(s.key_id) AS count
            FROM key_model_status AS s
            JOIN api_keys AS k ON s.key_id = k.id
            JOIN providers AS p ON k.provider_id = p.id
            GROUP BY p.name, s.model_name, s.status
            ORDER BY p.name, s.model_name, s.status
            """)


@pytest.mark.asyncio
async def test_get_status_summary_with_data():
    """Test get_status_summary returns correctly formatted StatusSummaryItems."""
    mock_pool = MagicMock()
    mock_accessor = MagicMock()
    repo = KeyRepository(mock_pool, mock_accessor)

    # Mock database rows
    mock_rows = [
        {
            "provider": "openai",
            "model": "gpt-4",
            "status": "valid",
            "count": 5,
        },
        {
            "provider": "openai",
            "model": "gpt-3.5-turbo",
            "status": "invalid",
            "count": 2,
        },
        {
            "provider": "anthropic",
            "model": "claude-3",
            "status": "valid",
            "count": 3,
        },
        {
            "provider": "anthropic",
            "model": "claude-2",
            "status": "untested",
            "count": 1,
        },
    ]
    mock_conn = MagicMock()
    mock_conn.fetch = AsyncMock(return_value=mock_rows)
    mock_pool.acquire.return_value.__aenter__.return_value = mock_conn

    result = await repo.get_status_summary()

    assert len(result) == 4
    # Verify structure matches StatusSummaryItem TypedDict
    for i, item in enumerate(result):
        assert "provider" in item
        assert "model" in item
        assert "status" in item
        assert "count" in item
        assert item["provider"] == mock_rows[i]["provider"]
        assert item["model"] == mock_rows[i]["model"]
        assert item["status"] == mock_rows[i]["status"]
        assert item["count"] == mock_rows[i]["count"]


@pytest.mark.asyncio
async def test_get_status_summary_with_shared_key_status_marker():
    """Test get_status_summary includes __ALL_MODELS__ marker for shared key providers."""
    mock_pool = MagicMock()
    mock_accessor = MagicMock()
    repo = KeyRepository(mock_pool, mock_accessor)

    # Mock database rows including ALL_MODELS_MARKER
    mock_rows = [
        {
            "provider": "shared_provider",
            "model": "__ALL_MODELS__",
            "status": "valid",
            "count": 10,
        },
        {
            "provider": "shared_provider",
            "model": "__ALL_MODELS__",
            "status": "invalid",
            "count": 1,
        },
    ]
    mock_conn = MagicMock()
    mock_conn.fetch = AsyncMock(return_value=mock_rows)
    mock_pool.acquire.return_value.__aenter__.return_value = mock_conn

    result = await repo.get_status_summary()

    assert len(result) == 2
    # Verify ALL_MODELS_MARKER is preserved
    assert any(item["model"] == "__ALL_MODELS__" for item in result)


@pytest.mark.asyncio
async def test_get_status_summary_query_includes_all_statuses():
    """Test get_status_summary includes all status values (valid, invalid, untested, etc.)."""
    mock_pool = MagicMock()
    mock_accessor = MagicMock()
    repo = KeyRepository(mock_pool, mock_accessor)

    # Mock database rows with various statuses
    mock_rows = [
        {"provider": "test", "model": "model1", "status": "valid", "count": 5},
        {"provider": "test", "model": "model1", "status": "invalid", "count": 2},
        {"provider": "test", "model": "model1", "status": "untested", "count": 3},
        {"provider": "test", "model": "model1", "status": "rate_limited", "count": 1},
        {"provider": "test", "model": "model1", "status": "quota_exceeded", "count": 1},
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
async def test_get_status_summary_grouping_correctness():
    """Test get_status_summary correctly groups by provider, model, and status."""
    mock_pool = MagicMock()
    mock_accessor = MagicMock()
    repo = KeyRepository(mock_pool, mock_accessor)

    # Mock database rows that would come from GROUP BY
    mock_rows = [
        {"provider": "p1", "model": "m1", "status": "valid", "count": 2},
        {"provider": "p1", "model": "m1", "status": "invalid", "count": 1},
        {"provider": "p1", "model": "m2", "status": "valid", "count": 3},
        {"provider": "p2", "model": "m1", "status": "valid", "count": 4},
    ]
    mock_conn = MagicMock()
    mock_conn.fetch = AsyncMock(return_value=mock_rows)
    mock_pool.acquire.return_value.__aenter__.return_value = mock_conn

    result = await repo.get_status_summary()

    # Should have exactly 4 groups
    assert len(result) == 4
    # Verify counts are correct
    for item in result:
        if (
            item["provider"] == "p1"
            and item["model"] == "m1"
            and item["status"] == "valid"
        ):
            assert item["count"] == 2
        elif (
            item["provider"] == "p1"
            and item["model"] == "m1"
            and item["status"] == "invalid"
        ):
            assert item["count"] == 1
        elif (
            item["provider"] == "p1"
            and item["model"] == "m2"
            and item["status"] == "valid"
        ):
            assert item["count"] == 3
        elif (
            item["provider"] == "p2"
            and item["model"] == "m1"
            and item["status"] == "valid"
        ):
            assert item["count"] == 4


@pytest.mark.asyncio
async def test_get_status_summary_database_error():
    """Test get_status_summary propagates database errors."""
    mock_pool = MagicMock()
    mock_accessor = MagicMock()
    repo = KeyRepository(mock_pool, mock_accessor)

    # Mock database error
    mock_conn = MagicMock()
    mock_conn.fetch = AsyncMock(side_effect=Exception("Database connection failed"))
    mock_pool.acquire.return_value.__aenter__.return_value = mock_conn

    with pytest.raises(Exception, match="Database connection failed"):
        await repo.get_status_summary()
