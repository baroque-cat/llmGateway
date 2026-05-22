#!/usr/bin/env python3

"""
Unit tests for KeyRepository.get_available_key() method.

Tests the retrieval of available VALID keys for a given provider and model.
All providers now uniformly substitute ALL_MODELS_MARKER.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.core.constants import ALL_MODELS_MARKER
from src.db.database import KeyRepository


def _make_repo_and_conn() -> tuple[KeyRepository, MagicMock]:
    """Build a KeyRepository with mocked pool and connection.

    Returns (repo, mock_conn).
    """
    mock_pool = MagicMock()
    mock_conn = MagicMock()

    # pool.acquire() returns async context manager → conn
    mock_pool.acquire.return_value.__aenter__.return_value = mock_conn

    # Default async methods on conn (no transaction needed for this method)
    mock_conn.fetchval = AsyncMock(return_value=None)
    mock_conn.fetchrow = AsyncMock(return_value=None)

    repo = KeyRepository(mock_pool)
    return repo, mock_conn


@pytest.mark.asyncio
async def test_get_available_key_returns_key():
    """When VALID keys exist in DB, a key dict is returned."""
    repo, mock_conn = _make_repo_and_conn()

    # Mock: count query returns 1 valid key
    mock_conn.fetchval = AsyncMock(return_value=1)
    # Mock: key retrieval returns a key
    mock_conn.fetchrow = AsyncMock(
        return_value={"key_id": 42, "key_value": "sk-test-key"}
    )

    result = await repo.get_available_key("test_provider", "model1")

    assert result is not None
    assert result["key_id"] == 42
    assert result["key_value"] == "sk-test-key"


@pytest.mark.asyncio
async def test_get_available_key_no_valid_keys():
    """When no VALID keys exist (count=0), returns None."""
    repo, mock_conn = _make_repo_and_conn()

    # Mock: count query returns 0
    mock_conn.fetchval = AsyncMock(return_value=0)

    result = await repo.get_available_key("test_provider", "model1")

    assert result is None
    # fetchrow should NOT be called when count is 0
    mock_conn.fetchrow.assert_not_called()


@pytest.mark.asyncio
async def test_get_available_key_returns_none_when_count_is_none():
    """When fetchval returns None (no matching rows), returns None."""
    repo, mock_conn = _make_repo_and_conn()

    # Mock: count query returns None
    mock_conn.fetchval = AsyncMock(return_value=None)

    result = await repo.get_available_key("test_provider", "model1")

    assert result is None
    mock_conn.fetchrow.assert_not_called()


@pytest.mark.asyncio
async def test_get_available_key_always_substitutes_all_models():
    """get_available_key always substitutes ALL_MODELS_MARKER for the model_name,
    regardless of what model name is passed in."""
    repo, mock_conn = _make_repo_and_conn()

    # Mock: count query returns 1 valid key
    mock_conn.fetchval = AsyncMock(return_value=1)
    mock_conn.fetchrow = AsyncMock(
        return_value={"key_id": 10, "key_value": "sk-test-key"}
    )

    result = await repo.get_available_key("any_provider", "gpt-4")

    assert result is not None
    assert result["key_id"] == 10

    # Verify fetchval was called with ALL_MODELS_MARKER as model_name ($2)
    fetchval_call = mock_conn.fetchval.call_args
    assert fetchval_call[0][2] == ALL_MODELS_MARKER

    # Verify fetchrow was called with ALL_MODELS_MARKER as model_name ($2)
    fetchrow_call = mock_conn.fetchrow.call_args
    assert fetchrow_call[0][2] == ALL_MODELS_MARKER


# ── get_all_valid_keys_for_caching ─────────────────────────────────────


@pytest.mark.asyncio
async def test_key_without_status_row_is_cached():
    """A key with no key_model_status row (COALESCE → '__ALL_MODELS__')
    is returned by get_all_valid_keys_for_caching()."""
    repo, mock_conn = _make_repo_and_conn()

    mock_rows = [
        {
            "key_id": 1,
            "provider_name": "provider1",
            "model_name": "__ALL_MODELS__",
            "key_value": "sk-key-no-status",
        },
        {
            "key_id": 2,
            "provider_name": "provider1",
            "model_name": "model-a",
            "key_value": "sk-key-with-status",
        },
    ]
    mock_conn.fetch = AsyncMock(return_value=mock_rows)

    result = await repo.get_all_valid_keys_for_caching()

    assert len(result) == 2
    assert result[0]["key_id"] == 1
    assert result[0]["model_name"] == "__ALL_MODELS__"
    assert result[0]["key_value"] == "sk-key-no-status"
    assert result[1]["key_id"] == 2
    assert result[1]["model_name"] == "model-a"
    assert result[1]["key_value"] == "sk-key-with-status"


@pytest.mark.asyncio
async def test_key_with_fatal_status_is_excluded():
    """Keys with fatal status (invalid_key, no_access, no_quota, no_model)
    are excluded by the SQL WHERE clause in get_all_valid_keys_for_caching()."""
    repo, mock_conn = _make_repo_and_conn()

    # Mock: DB only returns valid keys after SQL filtering
    mock_rows = [
        {
            "key_id": 1,
            "provider_name": "provider1",
            "model_name": "model-a",
            "key_value": "sk-valid-key",
        },
    ]
    mock_conn.fetch = AsyncMock(return_value=mock_rows)

    result = await repo.get_all_valid_keys_for_caching()

    assert len(result) == 1
    assert result[0]["key_value"] == "sk-valid-key"

    # Verify the query uses LEFT JOIN and filters out fatal statuses
    query = mock_conn.fetch.call_args[0][0]
    assert "LEFT JOIN key_model_status" in query
    assert "invalid_key" in query
    assert "no_access" in query
    assert "no_quota" in query
    assert "no_model" in query
    assert "COALESCE(s.model_name, '__ALL_MODELS__')" in query


@pytest.mark.asyncio
async def test_get_all_valid_keys_for_caching_returns_empty():
    """When no valid keys exist, get_all_valid_keys_for_caching returns an empty list."""
    repo, mock_conn = _make_repo_and_conn()

    mock_conn.fetch = AsyncMock(return_value=[])

    result = await repo.get_all_valid_keys_for_caching()

    assert result == []
