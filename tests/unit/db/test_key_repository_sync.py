#!/usr/bin/env python3

"""
Unit tests for KeyRepository.sync() method.

Tests the synchronization of keys and their model associations
for a single provider, using unified ALL_MODELS_MARKER behavior.
"""

import inspect
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

    # conn.transaction() returns async context manager
    mock_conn.transaction.return_value.__aenter__ = AsyncMock(return_value=None)
    mock_conn.transaction.return_value.__aexit__ = AsyncMock(return_value=None)

    # Default async methods on conn
    mock_conn.fetch = AsyncMock(return_value=[])
    mock_conn.execute = AsyncMock(return_value=None)
    mock_conn.copy_records_to_table = AsyncMock(return_value=None)

    repo = KeyRepository(mock_pool)
    return repo, mock_conn


@pytest.mark.asyncio
async def test_sync_adds_new_keys():
    """When keys_from_file contains keys not in DB, new keys are added
    via copy_records_to_table and their model associations are created."""
    repo, mock_conn = _make_repo_and_conn()

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

    await repo.sync("test_provider", 10, {"existing_key", "new_key1"})

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
async def test_sync_removes_legacy_per_model_rows():
    """sync removes legacy per-model rows when all providers now use
    ALL_MODELS_MARKER associations exclusively."""
    repo, mock_conn = _make_repo_and_conn()

    # Fetch sequence:
    # 1st: existing keys in DB
    # 2nd: all key IDs
    # 3rd: current model state includes legacy per-model rows
    mock_conn.fetch = AsyncMock(
        side_effect=[
            [{"id": 1, "key_value": "key1"}],
            [{"id": 1}],
            [
                {"key_id": 1, "model_name": "model1"},
                {"key_id": 1, "model_name": "model2"},
            ],
        ]
    )

    # All per-model rows are legacy — desired state is {(1, ALL_MODELS_MARKER)}
    await repo.sync("test_provider", 10, {"key1"})

    # Verify DELETE was executed for legacy model associations
    assert mock_conn.execute.called
    delete_query = mock_conn.execute.call_args[0][0]
    assert "DELETE FROM key_model_status" in delete_query


@pytest.mark.asyncio
async def test_sync_no_changes():
    """When keys_from_file and model associations match DB exactly,
    nothing is added or removed."""
    repo, mock_conn = _make_repo_and_conn()

    # Fetch sequence: everything already matches the desired ALL_MODELS_MARKER state
    mock_conn.fetch = AsyncMock(
        side_effect=[
            [{"id": 1, "key_value": "key1"}],
            [{"id": 1}],
            [{"key_id": 1, "model_name": ALL_MODELS_MARKER}],
        ]
    )

    await repo.sync("test_provider", 10, {"key1"})

    # No additions or removals
    mock_conn.copy_records_to_table.assert_not_called()
    mock_conn.execute.assert_not_called()


@pytest.mark.asyncio
async def test_sync_with_empty_desired_keys():
    """When keys_from_file is empty, no new keys are added (Add-Only logic).

    Existing keys remain in DB. Their model associations are still synced
    to use ALL_MODELS_MARKER.
    """
    repo, mock_conn = _make_repo_and_conn()

    # Fetch sequence:
    # 1st: existing keys in DB (but keys_from_file is empty)
    # 2nd: all key IDs (existing keys remain)
    # 3rd: current model state already uses ALL_MODELS_MARKER
    mock_conn.fetch = AsyncMock(
        side_effect=[
            [{"id": 1, "key_value": "existing_key"}],
            [{"id": 1}],
            [{"key_id": 1, "model_name": ALL_MODELS_MARKER}],
        ]
    )

    # keys_from_file is empty set — Add-Only logic means no deletions from api_keys
    await repo.sync("test_provider", 10, set())

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


# ── New tests for unified ALL_MODELS_MARKER behavior ───────────────────


@pytest.mark.asyncio
async def test_sync_all_providers_use_all_models_marker():
    """sync creates ALL_MODELS_MARKER associations for any provider."""
    repo, mock_conn = _make_repo_and_conn()

    # Fetch: existing key, new key-model association needed
    mock_conn.fetch = AsyncMock(
        side_effect=[
            [{"id": 1, "key_value": "key1"}],
            [{"id": 1}],
            [],
        ]
    )

    await repo.sync("any_provider", 10, {"key1"})

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


def test_sync_signature_no_provider_models_param():
    """sync() signature excludes provider_models."""
    sig = inspect.signature(KeyRepository.sync)
    param_names = set(sig.parameters.keys())

    assert "provider_models" not in param_names
    assert "provider_name" in param_names
    assert "provider_id" in param_names
    assert "keys_from_file" in param_names
