#!/usr/bin/env python3

"""Unit tests for ProviderRepository.sync() — tests N45-N48.

Verifies that ProviderRepository.sync() delegates provider deletion to
IKeyPurger.purge_provider() instead of executing DELETE FROM providers
directly, and that new providers are added via copy_records_to_table.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.db.database import ProviderRepository


def _make_repo_and_deps(
    db_rows: list[dict] | None = None,
    purge_return: int = 3,
) -> tuple[ProviderRepository, MagicMock, MagicMock, MagicMock]:
    """Build a ProviderRepository with fully mocked pool, key_purger, and db_manager.

    Returns (repo, mock_conn, mock_key_purger, mock_db_manager).
    """
    mock_pool = MagicMock()
    mock_conn = MagicMock()

    # Make mock_conn work as async context manager for pool.acquire()
    mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_conn.__aexit__ = AsyncMock(return_value=None)

    # Make conn.transaction() return an async context manager
    mock_conn.transaction.return_value.__aenter__ = AsyncMock(return_value=None)
    mock_conn.transaction.return_value.__aexit__ = AsyncMock(return_value=None)

    # Default DB rows: one existing provider
    if db_rows is None:
        db_rows = [{"name": "existing-provider", "id": 1}]

    mock_conn.fetch = AsyncMock(return_value=db_rows)
    mock_conn.copy_records_to_table = AsyncMock(return_value=None)
    mock_conn.execute = AsyncMock(return_value=None)

    # pool.acquire() returns mock_conn directly
    mock_pool.acquire = MagicMock(return_value=mock_conn)

    mock_key_purger = MagicMock()
    mock_key_purger.purge_provider = AsyncMock(return_value=purge_return)

    mock_db_manager = MagicMock()

    repo = ProviderRepository(mock_pool, mock_key_purger)
    return repo, mock_conn, mock_key_purger, mock_db_manager


@pytest.mark.asyncio
async def test_provider_sync_delegates_deletion_to_key_purger():
    """N45: sync() with obsolete provider delegates deletion to KeyPurger.

    When a provider exists in the DB but not in config, sync() should call
    key_purger.purge_provider() with the correct provider_id and db_manager.
    """
    repo, mock_conn, mock_key_purger, mock_db_manager = _make_repo_and_deps(
        db_rows=[{"name": "obsolete-provider", "id": 42}]
    )

    await repo.sync(["new-provider"], mock_db_manager)

    mock_key_purger.purge_provider.assert_called_once_with(42, mock_db_manager)


@pytest.mark.asyncio
async def test_provider_sync_does_not_execute_delete_from_providers_directly():
    """N46: sync() does NOT execute DELETE FROM providers directly.

    Even when an obsolete provider is discovered, sync() should delegate
    deletion to KeyPurger rather than executing a DELETE FROM providers
    query on the connection.
    """
    repo, mock_conn, mock_key_purger, mock_db_manager = _make_repo_and_deps(
        db_rows=[{"name": "obsolete-provider", "id": 42}]
    )

    await repo.sync(["new-provider"], mock_db_manager)

    # Verify conn.execute was never called with a query containing "DELETE FROM providers"
    for call_args in mock_conn.execute.call_args_list:
        query = call_args[0][0] if call_args[0] else ""
        assert "DELETE FROM providers" not in query


@pytest.mark.asyncio
async def test_provider_sync_adds_new_providers():
    """N47: sync() adds new providers via copy_records_to_table.

    When config contains providers not yet in the DB, sync() should call
    conn.copy_records_to_table for the "providers" table with the new names.
    """
    repo, mock_conn, mock_key_purger, mock_db_manager = _make_repo_and_deps(
        db_rows=[{"name": "existing-provider", "id": 1}]
    )

    await repo.sync(["existing-provider", "brand-new"], mock_db_manager)

    mock_conn.copy_records_to_table.assert_called_once_with(
        "providers",
        records=[("brand-new",)],
        columns=["name"],
    )


@pytest.mark.asyncio
async def test_provider_sync_no_changes():
    """N48: When DB and config match, neither additions nor deletions happen.

    If the set of provider names in config exactly matches the DB, sync()
    should not call copy_records_to_table or purge_provider.
    """
    repo, mock_conn, mock_key_purger, mock_db_manager = _make_repo_and_deps(
        db_rows=[{"name": "provider-a", "id": 1}]
    )

    await repo.sync(["provider-a"], mock_db_manager)

    mock_conn.copy_records_to_table.assert_not_called()
    mock_key_purger.purge_provider.assert_not_called()
