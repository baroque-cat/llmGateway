"""Unit tests for CapacityAwareHTTPConnection in src.core.http2.connection."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpcore._async.http11 import AsyncHTTP11Connection
from httpcore._models import Origin

from src.core.http2.connection import CapacityAwareHTTPConnection
from src.core.http2.h2_connection import FixedHTTP2Connection


class TestCapacityAwareHTTPConnection:
    """Tests for CapacityAwareHTTPConnection."""

    @pytest.mark.asyncio
    async def test_creates_fixed_h2_on_alpn(self) -> None:
        """When ALPN negotiates h2, FixedHTTP2Connection is created."""
        origin = Origin(b"https", b"example.com", 443)

        conn = CapacityAwareHTTPConnection(
            origin=origin,
            http1=True,
            http2=True,
            retries=0,
        )

        # Mock the _connect to return a stream with h2 ALPN
        mock_stream = MagicMock()
        mock_ssl_object = MagicMock()
        mock_ssl_object.selected_alpn_protocol.return_value = "h2"
        mock_stream.get_extra_info.return_value = mock_ssl_object
        conn._connect = AsyncMock(return_value=mock_stream)  # type: ignore[reportPrivateUsage]

        mock_req = MagicMock()
        mock_req.url.origin = origin
        conn.can_handle_request = MagicMock(return_value=True)

        # Mock the inner connection's handle_async_request to avoid deep init
        with patch.object(
            FixedHTTP2Connection,
            "handle_async_request",
            new_callable=AsyncMock,
            return_value=MagicMock(),
        ):
            await conn.handle_async_request(mock_req)

        assert isinstance(conn._connection, FixedHTTP2Connection)  # type: ignore[reportPrivateUsage]

    @pytest.mark.asyncio
    async def test_creates_http11_on_no_alpn(self) -> None:
        """When ALPN does not negotiate h2, AsyncHTTP11Connection is created."""
        origin = Origin(b"https", b"example.com", 443)

        conn = CapacityAwareHTTPConnection(
            origin=origin,
            http1=True,
            http2=True,
            retries=0,
        )

        # Mock the _connect to return a stream WITHOUT h2 ALPN
        mock_stream = MagicMock()
        mock_ssl_object = MagicMock()
        mock_ssl_object.selected_alpn_protocol.return_value = "http/1.1"
        mock_stream.get_extra_info.return_value = mock_ssl_object
        conn._connect = AsyncMock(return_value=mock_stream)  # type: ignore[reportPrivateUsage]

        mock_req = MagicMock()
        mock_req.url.origin = origin
        conn.can_handle_request = MagicMock(return_value=True)

        with patch.object(
            AsyncHTTP11Connection,
            "handle_async_request",
            new_callable=AsyncMock,
            return_value=MagicMock(),
        ):
            await conn.handle_async_request(mock_req)

        assert isinstance(conn._connection, AsyncHTTP11Connection)  # type: ignore[reportPrivateUsage]
