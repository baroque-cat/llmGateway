#!/usr/bin/env python3

"""
Unit tests for KeyRepository.update_status() method.

Tests the update of key-model status records, including
failing_since management and shared_key_status handling.
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.core.constants import ALL_MODELS_MARKER, ErrorReason, Status
from src.core.models import CheckResult
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
    mock_conn.execute = AsyncMock(return_value=None)

    # Provider config
    mock_provider_config = MagicMock()
    mock_provider_config.shared_key_status = provider_config_shared
    mock_accessor.get_provider.return_value = mock_provider_config

    repo = KeyRepository(mock_pool, mock_accessor)
    return repo, mock_conn, mock_accessor


@pytest.mark.asyncio
async def test_update_status_sets_fields():
    """Verify that update_status correctly sets status, next_check_time,
    response_time, and other fields from a successful CheckResult."""
    repo, mock_conn, _ = _make_repo_and_conn()

    result = CheckResult.success(
        message="Key is valid",
        response_time=150.0,
        status_code=200,
    )
    next_check_time = datetime(2025, 6, 1, 12, 0, 0, tzinfo=UTC)

    await repo.update_status(1, "model1", "test_provider", result, next_check_time)

    # Verify conn.execute was called
    assert mock_conn.execute.called

    # Extract the query and params
    call_args = mock_conn.execute.call_args
    query = call_args[0][0]
    params = call_args[0][1:]

    # Verify key fragments of the UPDATE query
    assert "UPDATE key_model_status" in query
    assert "status" in query
    assert "next_check_time" in query
    assert "response_time" in query
    assert "failing_since" in query

    # Verify params: status_str should be "valid" for a successful result
    assert params[0] == Status.VALID  # status
    assert params[1] == next_check_time  # next_check_time
    assert params[2] == 200  # status_code
    assert params[3] == 150.0  # response_time


@pytest.mark.asyncio
async def test_update_status_shared_key_affects_all_models():
    """When shared_key_status=True, the WHERE clause uses ALL_MODELS_MARKER
    instead of the specific model_name, so the update affects all models."""
    repo, mock_conn, _ = _make_repo_and_conn(provider_config_shared=True)

    result = CheckResult.success(message="OK", response_time=100.0, status_code=200)
    next_check_time = datetime(2025, 6, 1, 12, 0, 0, tzinfo=UTC)

    await repo.update_status(5, "gpt-4", "shared_provider", result, next_check_time)

    call_args = mock_conn.execute.call_args
    params = call_args[0][1:]

    # The last two params ($7, $8) should be key_id and ALL_MODELS_MARKER
    assert params[6] == 5  # key_id ($7)
    assert params[7] == ALL_MODELS_MARKER  # model_name ($8)


@pytest.mark.asyncio
async def test_update_status_non_shared_updates_single_row():
    """When shared_key_status=False, the WHERE clause uses the specific
    model_name, so only one key-model row is updated."""
    repo, mock_conn, _ = _make_repo_and_conn(provider_config_shared=False)

    result = CheckResult.success(message="OK", response_time=100.0, status_code=200)
    next_check_time = datetime(2025, 6, 1, 12, 0, 0, tzinfo=UTC)

    await repo.update_status(5, "gpt-4", "normal_provider", result, next_check_time)

    call_args = mock_conn.execute.call_args
    params = call_args[0][1:]

    # The last two params ($7, $8) should be key_id and the actual model_name
    assert params[6] == 5  # key_id ($7)
    assert params[7] == "gpt-4"  # model_name ($8)


@pytest.mark.asyncio
async def test_update_status_sets_failing_since_when_error():
    """When the check result is an error (not OK), failing_since is set
    via COALESCE(failing_since, NOW()) — preserving an existing timestamp
    or setting a new one."""
    repo, mock_conn, _ = _make_repo_and_conn()

    result = CheckResult.fail(
        reason=ErrorReason.RATE_LIMITED,
        message="Rate limited",
        response_time=50.0,
        status_code=429,
    )
    next_check_time = datetime(2025, 6, 1, 12, 0, 0, tzinfo=UTC)

    await repo.update_status(1, "model1", "test_provider", result, next_check_time)

    call_args = mock_conn.execute.call_args
    query = call_args[0][0]
    params = call_args[0][1:]

    # Status should be the error reason value
    assert params[0] == ErrorReason.RATE_LIMITED.value  # "rate_limited"

    # result.ok is False, so $6 (the CASE boolean) is False
    # → failing_since = COALESCE(failing_since, NOW())
    assert params[5] is False  # result.ok

    # The CASE in the query should use COALESCE for failing_since
    assert "COALESCE" in query
    assert "failing_since" in query


@pytest.mark.asyncio
async def test_update_status_resets_failing_since_when_valid():
    """When the check result is OK (valid), failing_since is set to NULL,
    resetting any previous failure tracking."""
    repo, mock_conn, _ = _make_repo_and_conn()

    result = CheckResult.success(message="Key is valid", response_time=100.0)
    next_check_time = datetime(2025, 6, 1, 12, 0, 0, tzinfo=UTC)

    await repo.update_status(1, "model1", "test_provider", result, next_check_time)

    call_args = mock_conn.execute.call_args
    query = call_args[0][0]
    params = call_args[0][1:]

    # result.ok is True, so $6 is True → CASE WHEN $6 THEN NULL
    assert params[5] is True  # result.ok

    # The query should contain NULL for the failing_since reset
    assert "NULL" in query


@pytest.mark.asyncio
async def test_update_status_with_untested_status():
    """Verify update_status correctly handles a non-VALID error status.

    The method computes status_str = Status.VALID if result.ok else
    result.error_reason.value. Since UNTESTED cannot be produced from
    a CheckResult, this test verifies correct handling of a fatal error
    status (INVALID_KEY) and that the assertion status_str in Status passes.
    """
    repo, mock_conn, _ = _make_repo_and_conn()

    result = CheckResult.fail(
        reason=ErrorReason.INVALID_KEY,
        message="Invalid API key",
        response_time=200.0,
        status_code=401,
    )
    next_check_time = datetime(2025, 6, 1, 12, 0, 0, tzinfo=UTC)

    await repo.update_status(1, "model1", "test_provider", result, next_check_time)

    call_args = mock_conn.execute.call_args
    params = call_args[0][1:]

    # Status should be the error reason value ("invalid_key")
    assert params[0] == ErrorReason.INVALID_KEY.value

    # result.ok is False → failing_since = COALESCE(failing_since, NOW())
    assert params[5] is False
