"""Tests for KeyRepository.update_status() with transport_failure parameter.

Verifies that:
- transport_failure=True omits status and failing_since from UPDATE
- transport_failure=False includes status and failing_since in UPDATE
- Parameters are ordered correctly in both paths
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.core.constants import ErrorReason, TransportFailureClass
from src.core.models import CheckResult
from src.db.database import KeyRepository
from tests._canonical import CanonicalConfig


@pytest.fixture
def mock_pool():
    """Create a mock asyncpg pool."""
    pool = MagicMock()
    conn = AsyncMock()
    conn.transaction = MagicMock()
    conn.transaction.return_value.__aenter__ = AsyncMock(return_value=None)
    conn.transaction.return_value.__aexit__ = AsyncMock(return_value=None)
    pool.acquire = MagicMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)
    return pool, conn


@pytest.fixture
def key_repo(mock_pool):
    """Create a KeyRepository with mocked pool."""
    pool, conn = mock_pool
    repo = KeyRepository(pool)
    return repo, conn


@pytest.mark.asyncio
async def test_update_status_transport_failure_omits_status_and_failing_since(
    key_repo,
):
    """transport_failure=True must NOT include status= or failing_since in SQL."""
    repo, conn = key_repo
    key_id = 123
    model_name = CanonicalConfig.from_example_files().canonical_model_names[0]
    provider_name = "openai"
    result = CheckResult.fail(
        ErrorReason.NETWORK_ERROR,
        "Connection timeout",
        transport_class=TransportFailureClass.CONNECT_TIMEOUT,
    )
    next_check_time = datetime.now(UTC) + timedelta(minutes=5)

    await repo.update_status(
        key_id=key_id,
        model_name=model_name,
        provider_name=provider_name,
        result=result,
        next_check_time=next_check_time,
        transport_failure=True,
    )

    # Verify execute was called
    conn.execute.assert_awaited_once()
    query = conn.execute.call_args[0][0]

    # SQL must NOT contain status= or failing_since
    assert "status =" not in query.lower()
    assert "failing_since" not in query.lower()

    # SQL must contain last_checked and next_check_time
    assert "last_checked" in query.lower()
    assert "next_check_time" in query.lower()

    # Verify parameters: next_check_time, status_code, response_time, error_message, key_id, model_name
    params = conn.execute.call_args[0][1:]
    assert len(params) == 6
    assert params[0] == next_check_time  # $1
    assert params[1] == result.status_code  # $2
    assert params[2] == result.response_time  # $3
    assert params[3] == result.message[:1000]  # $4
    assert params[4] == key_id  # $5
    # $6 is ALL_MODELS_MARKER (imported constant)


@pytest.mark.asyncio
async def test_update_status_normal_path_includes_status_and_failing_since(
    key_repo,
):
    """transport_failure=False must include status= and failing_since in SQL."""
    repo, conn = key_repo
    key_id = 456
    model_name = CanonicalConfig.from_example_files().canonical_model_names[0]
    provider_name = "openai"
    result = CheckResult.fail(ErrorReason.INVALID_KEY, "Invalid API key")
    next_check_time = datetime.now(UTC) + timedelta(hours=1)

    await repo.update_status(
        key_id=key_id,
        model_name=model_name,
        provider_name=provider_name,
        result=result,
        next_check_time=next_check_time,
        transport_failure=False,
    )

    # Verify execute was called
    conn.execute.assert_awaited_once()
    query = conn.execute.call_args[0][0]

    # SQL must contain status= and failing_since
    assert "status =" in query.lower()
    assert "failing_since" in query.lower()

    # SQL must also contain last_checked and next_check_time
    assert "last_checked" in query.lower()
    assert "next_check_time" in query.lower()

    # Verify parameters: status, next_check_time, status_code, response_time, error_message, ok, key_id, model_name
    params = conn.execute.call_args[0][1:]
    assert len(params) == 8
    assert params[0] == result.error_reason.value  # $1 (status)
    assert params[1] == next_check_time  # $2
    assert params[2] == result.status_code  # $3
    assert params[3] == result.response_time  # $4
    assert params[4] == result.message[:1000]  # $5
    assert params[5] == result.ok  # $6 (for failing_since CASE)
    assert params[6] == key_id  # $7
    # $8 is ALL_MODELS_MARKER


@pytest.mark.asyncio
async def test_update_status_transport_failure_success_result(key_repo):
    """transport_failure=True with a success result still omits status update."""
    repo, conn = key_repo
    key_id = 789
    model_name = CanonicalConfig.from_example_files().canonical_model_names[0]
    provider_name = "openai"
    result = CheckResult.success()
    next_check_time = datetime.now(UTC) + timedelta(hours=2)

    await repo.update_status(
        key_id=key_id,
        model_name=model_name,
        provider_name=provider_name,
        result=result,
        next_check_time=next_check_time,
        transport_failure=True,
    )

    query = conn.execute.call_args[0][0]

    # Even with success, transport_failure=True must omit status
    assert "status =" not in query.lower()
    assert "failing_since" not in query.lower()


@pytest.mark.asyncio
async def test_update_status_default_transport_failure_is_false(key_repo):
    """Default transport_failure parameter is False (backward compatibility)."""
    repo, conn = key_repo
    key_id = 101
    model_name = CanonicalConfig.from_example_files().canonical_model_names[0]
    provider_name = "openai"
    result = CheckResult.fail(ErrorReason.RATE_LIMITED, "Rate limited")
    next_check_time = datetime.now(UTC) + timedelta(minutes=15)

    # Call without transport_failure parameter
    await repo.update_status(
        key_id=key_id,
        model_name=model_name,
        provider_name=provider_name,
        result=result,
        next_check_time=next_check_time,
    )

    query = conn.execute.call_args[0][0]

    # Default behavior should include status
    assert "status =" in query.lower()
    assert "failing_since" in query.lower()
