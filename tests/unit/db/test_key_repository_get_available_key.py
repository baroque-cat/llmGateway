#!/usr/bin/env python3

"""
Unit tests for KeyRepository.get_available_key() method.

Tests the retrieval of available VALID keys for a given provider and model,
including shared_key_status handling and the no-keys-available edge case.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.core.constants import ALL_MODELS_MARKER
from src.db.database import KeyRepository


def _make_repo_and_conn(
    provider_config_shared: bool = False,
) -> tuple[KeyRepository, MagicMock, MagicMock]:
    """Build a KeyRepository with mocked pool, accessor, and connection.

    Returns (repo, mock_conn, mock_accessor).
    """
    mock_pool = MagicMock()
    mock_accessor = MagicMock()
    mock_conn = MagicMock()

    # pool.acquire() returns async context manager → conn
    mock_pool.acquire.return_value.__aenter__.return_value = mock_conn

    # Default async methods on conn (no transaction needed for this method)
    mock_conn.fetchval = AsyncMock(return_value=None)
    mock_conn.fetchrow = AsyncMock(return_value=None)

    # Provider config
    mock_provider_config = MagicMock()
    mock_provider_config.shared_key_status = provider_config_shared
    mock_accessor.get_provider.return_value = mock_provider_config

    repo = KeyRepository(mock_pool, mock_accessor)
    return repo, mock_conn, mock_accessor


@pytest.mark.asyncio
async def test_get_available_key_returns_key():
    """When VALID keys exist in DB, a key dict is returned."""
    repo, mock_conn, _ = _make_repo_and_conn()

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
    repo, mock_conn, _ = _make_repo_and_conn()

    # Mock: count query returns 0
    mock_conn.fetchval = AsyncMock(return_value=0)

    result = await repo.get_available_key("test_provider", "model1")

    assert result is None
    # fetchrow should NOT be called when count is 0
    mock_conn.fetchrow.assert_not_called()


@pytest.mark.asyncio
async def test_get_available_key_returns_none_when_count_is_none():
    """When fetchval returns None (no matching rows), returns None."""
    repo, mock_conn, _ = _make_repo_and_conn()

    # Mock: count query returns None
    mock_conn.fetchval = AsyncMock(return_value=None)

    result = await repo.get_available_key("test_provider", "model1")

    assert result is None
    mock_conn.fetchrow.assert_not_called()


@pytest.mark.asyncio
async def test_get_available_key_with_shared_key_status():
    """When shared_key_status=True, queries use ALL_MODELS_MARKER
    as the model_name parameter."""
    repo, mock_conn, _ = _make_repo_and_conn(provider_config_shared=True)

    # Mock: count query returns 1 valid key
    mock_conn.fetchval = AsyncMock(return_value=1)
    mock_conn.fetchrow = AsyncMock(
        return_value={"key_id": 10, "key_value": "sk-shared-key"}
    )

    result = await repo.get_available_key("shared_provider", "gpt-4")

    assert result is not None
    assert result["key_id"] == 10

    # Verify fetchval was called with ALL_MODELS_MARKER as model_name ($2)
    fetchval_call = mock_conn.fetchval.call_args
    assert fetchval_call[0][2] == ALL_MODELS_MARKER

    # Verify fetchrow was called with ALL_MODELS_MARKER as model_name ($2)
    fetchrow_call = mock_conn.fetchrow.call_args
    assert fetchrow_call[0][2] == ALL_MODELS_MARKER


@pytest.mark.asyncio
async def test_get_available_key_prefers_specific_model():
    """For non-shared providers, queries use the specific model_name.
    For shared providers, queries use ALL_MODELS_MARKER.

    Both paths produce correct results with their respective model names.
    """
    # --- Non-shared provider: uses actual model_name ---
    repo_ns, mock_conn_ns, _ = _make_repo_and_conn(provider_config_shared=False)
    mock_conn_ns.fetchval = AsyncMock(return_value=1)
    mock_conn_ns.fetchrow = AsyncMock(
        return_value={"key_id": 1, "key_value": "sk-specific"}
    )

    result_ns = await repo_ns.get_available_key("provider", "gpt-4")
    assert result_ns is not None
    # fetchval should use the actual model_name ($2)
    fetchval_call_ns = mock_conn_ns.fetchval.call_args
    assert fetchval_call_ns[0][2] == "gpt-4"

    # --- Shared provider: uses ALL_MODELS_MARKER ---
    repo_s, mock_conn_s, _ = _make_repo_and_conn(provider_config_shared=True)
    mock_conn_s.fetchval = AsyncMock(return_value=1)
    mock_conn_s.fetchrow = AsyncMock(
        return_value={"key_id": 2, "key_value": "sk-shared"}
    )

    result_s = await repo_s.get_available_key("shared_provider", "gpt-4")
    assert result_s is not None
    # fetchval should use ALL_MODELS_MARKER ($2)
    fetchval_call_s = mock_conn_s.fetchval.call_args
    assert fetchval_call_s[0][2] == ALL_MODELS_MARKER
