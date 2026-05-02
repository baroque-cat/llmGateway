#!/usr/bin/env python3

"""
Unit tests for KeyRepository.sync() method.

Tests the synchronization of keys and their model associations
for a single provider, including add-only key logic and
model association add/remove logic.
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

    # conn.transaction() returns async context manager
    mock_conn.transaction.return_value.__aenter__ = AsyncMock(return_value=None)
    mock_conn.transaction.return_value.__aexit__ = AsyncMock(return_value=None)

    # Default async methods on conn
    mock_conn.fetch = AsyncMock(return_value=[])
    mock_conn.execute = AsyncMock(return_value=None)
    mock_conn.copy_records_to_table = AsyncMock(return_value=None)

    # Provider config
    mock_provider_config = MagicMock()
    mock_provider_config.shared_key_status = provider_config_shared
    mock_accessor.get_provider.return_value = mock_provider_config

    repo = KeyRepository(mock_pool, mock_accessor)
    return repo, mock_conn, mock_accessor


@pytest.mark.asyncio
async def test_sync_adds_new_keys():
    """When keys_from_file contains keys not in DB, new keys are added
    via copy_records_to_table and their model associations are created."""
    repo, mock_conn, _ = _make_repo_and_conn()

    # Fetch call sequence:
    # 1st: SELECT id, key_value FROM api_keys → existing keys
    # 2nd: SELECT id FROM api_keys → all key IDs (after potential addition)
    # 3rd: SELECT key_id, model_name FROM key_model_status → current model state
    mock_conn.fetch = AsyncMock(
        side_effect=[
            [{"id": 1, "key_value": "existing_key"}],
            [{"id": 1}, {"id": 2}],
            [],
        ]
    )

    await repo.sync("test_provider", 10, {"existing_key", "new_key1"}, ["model1"])

    # Verify copy_records_to_table was called for api_keys (adding new_key1)
    api_calls = [
        c
        for c in mock_conn.copy_records_to_table.call_args_list
        if c[0][0] == "api_keys"
    ]
    assert len(api_calls) == 1
    records = api_calls[0][1]["records"]
    assert (10, "new_key1") in records

    # Verify copy_records_to_table was called for key_model_status (new associations)
    model_calls = [
        c
        for c in mock_conn.copy_records_to_table.call_args_list
        if c[0][0] == "key_model_status"
    ]
    assert len(model_calls) == 1


@pytest.mark.asyncio
async def test_sync_removes_orphaned_keys():
    """Obsolete key-model associations not in the desired state are removed via DELETE.

    Note: The actual sync() uses Add-Only logic for api_keys — keys are NOT
    removed from the api_keys table when absent from keys_from_file.
    Only key-model associations in key_model_status can be removed.
    """
    repo, mock_conn, _ = _make_repo_and_conn()

    # Fetch sequence:
    # 1st: existing keys in DB
    # 2nd: all key IDs
    # 3rd: current model state includes an obsolete model association
    mock_conn.fetch = AsyncMock(
        side_effect=[
            [{"id": 1, "key_value": "key1"}, {"id": 2, "key_value": "key2"}],
            [{"id": 1}, {"id": 2}],
            [
                {"key_id": 1, "model_name": "model1"},
                {"key_id": 2, "model_name": "model1"},
                {"key_id": 2, "model_name": "obsolete_model"},
            ],
        ]
    )

    # provider_models = ["model1"] → "obsolete_model" is not in desired state
    await repo.sync("test_provider", 10, {"key1", "key2"}, ["model1"])

    # Verify DELETE was executed for obsolete model associations
    assert mock_conn.execute.called
    delete_query = mock_conn.execute.call_args[0][0]
    assert "DELETE FROM key_model_status" in delete_query
    # The obsolete_model should appear in the query parameters
    assert "obsolete_model" in mock_conn.execute.call_args[0]


@pytest.mark.asyncio
async def test_sync_no_changes():
    """When keys_from_file and model associations match DB exactly,
    nothing is added or removed."""
    repo, mock_conn, _ = _make_repo_and_conn()

    # Fetch sequence: everything matches perfectly
    mock_conn.fetch = AsyncMock(
        side_effect=[
            [{"id": 1, "key_value": "key1"}],
            [{"id": 1}],
            [{"key_id": 1, "model_name": "model1"}],
        ]
    )

    await repo.sync("test_provider", 10, {"key1"}, ["model1"])

    # No additions or removals
    mock_conn.copy_records_to_table.assert_not_called()
    mock_conn.execute.assert_not_called()


@pytest.mark.asyncio
async def test_sync_with_shared_key_status():
    """When shared_key_status=True, model associations use ALL_MODELS_MARKER
    instead of individual model names."""
    repo, mock_conn, _ = _make_repo_and_conn(provider_config_shared=True)

    # Fetch sequence:
    # 1st: existing keys
    # 2nd: all key IDs
    # 3rd: current model state is empty (all new associations)
    mock_conn.fetch = AsyncMock(
        side_effect=[
            [{"id": 1, "key_value": "key1"}],
            [{"id": 1}],
            [],
        ]
    )

    await repo.sync("test_provider", 10, {"key1"}, ["model1", "model2"])

    # Verify key_model_status records use ALL_MODELS_MARKER
    model_calls = [
        c
        for c in mock_conn.copy_records_to_table.call_args_list
        if c[0][0] == "key_model_status"
    ]
    assert len(model_calls) == 1
    records = model_calls[0][1]["records"]
    # Each record: (key_id, model_name, status, failing_since, next_check_time)
    for rec in records:
        assert rec[1] == ALL_MODELS_MARKER


@pytest.mark.asyncio
async def test_sync_with_empty_desired_keys():
    """When keys_from_file is empty, no new keys are added (Add-Only logic).

    Existing keys remain in DB. Their model associations are still synced
    based on provider_models.
    """
    repo, mock_conn, _ = _make_repo_and_conn()

    # Fetch sequence:
    # 1st: existing keys in DB (but keys_from_file is empty)
    # 2nd: all key IDs (existing keys remain)
    # 3rd: current model state matches desired
    mock_conn.fetch = AsyncMock(
        side_effect=[
            [{"id": 1, "key_value": "existing_key"}],
            [{"id": 1}],
            [{"key_id": 1, "model_name": "model1"}],
        ]
    )

    # keys_from_file is empty set — Add-Only logic means no deletions from api_keys
    await repo.sync("test_provider", 10, set(), ["model1"])

    # No new keys should be added (empty - existing = empty)
    api_calls = [
        c
        for c in mock_conn.copy_records_to_table.call_args_list
        if c[0][0] == "api_keys"
    ]
    assert len(api_calls) == 0

    # No model changes (desired matches current)
    model_calls = [
        c
        for c in mock_conn.copy_records_to_table.call_args_list
        if c[0][0] == "key_model_status"
    ]
    assert len(model_calls) == 0
    mock_conn.execute.assert_not_called()


@pytest.mark.asyncio
async def test_sync_with_empty_models():
    """When provider_models is empty, all existing model associations are removed."""
    repo, mock_conn, _ = _make_repo_and_conn()

    # Fetch sequence:
    # 1st: existing keys
    # 2nd: all key IDs
    # 3rd: current model state has associations that will become obsolete
    mock_conn.fetch = AsyncMock(
        side_effect=[
            [{"id": 1, "key_value": "key1"}],
            [{"id": 1}],
            [{"key_id": 1, "model_name": "old_model"}],
        ]
    )

    # provider_models = [] → desired_model_state = {} → all associations removed
    await repo.sync("test_provider", 10, {"key1"}, [])

    # Verify DELETE was called to remove all model associations
    assert mock_conn.execute.called
    delete_query = mock_conn.execute.call_args[0][0]
    assert "DELETE FROM key_model_status" in delete_query
