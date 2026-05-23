"""Verify asyncpg's connect() accepts timeout as a keyword argument."""

import inspect

import asyncpg
import pytest


@pytest.mark.asyncio
async def test_asyncpg_connect_accepts_timeout_kwarg():
    """asyncpg.connect() signature must include 'timeout' parameter.

    This catches the original bug class (wrong keyword argument name)
    at CI time without needing a live PostgreSQL connection.
    """
    sig = inspect.signature(asyncpg.connect)
    assert "timeout" in sig.parameters, (
        f"asyncpg.connect() does not accept 'timeout' — "
        f"parameters are: {list(sig.parameters.keys())}"
    )
