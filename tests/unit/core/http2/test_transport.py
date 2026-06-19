"""Unit tests for CapacityAwareHttp2Pool in src.core.http2.pool."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpcore._models import Origin

from src.core.http2.pool import CapacityAwareHttp2Pool


class TestCapacityAwareHttp2Pool:
    """Tests for CapacityAwareHttp2Pool."""

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _make_pool(**kwargs: object) -> CapacityAwareHttp2Pool:
        """Create a CapacityAwareHttp2Pool with default settings."""
        defaults: dict[str, object] = {
            "max_connections": 10,
            "max_keepalive_connections": 5,
            "http1": True,
            "http2": True,
        }
        defaults.update(kwargs)
        return CapacityAwareHttp2Pool(**defaults)  # type: ignore[arg-type]

    @staticmethod
    def _make_mock_connection(
        is_available: bool = True,
        is_idle: bool = False,
        is_closed: bool = False,
        has_expired: bool = False,
        can_handle: bool = True,
        max_conc_val: int = 100,
        has_max_conc: bool = True,
    ) -> MagicMock:
        """Create a mock connection for pool tests."""
        # No spec — max_concurrent_requests not in AsyncConnectionInterface
        conn = MagicMock()
        conn.is_available.return_value = is_available
        conn.is_idle.return_value = is_idle
        conn.is_closed.return_value = is_closed
        conn.has_expired.return_value = has_expired
        conn.can_handle_request.return_value = can_handle
        if has_max_conc:
            conn.max_concurrent_requests.return_value = max_conc_val
        else:
            del conn.max_concurrent_requests
        return conn

    @staticmethod
    def _make_mock_pool_request(
        origin: Origin | None = None,
        queued: bool = True,
        connection: object | None = None,
    ) -> MagicMock:
        """Create a mock pool request for pool tests."""
        req = MagicMock()
        req.is_queued.return_value = queued
        req.connection = connection

        if origin is None:
            origin = Origin(b"https", b"example.com", 443)

        inner_req = MagicMock()
        inner_req.url.origin = origin
        req.request = inner_req

        req.assign_to_connection = MagicMock()
        return req

    # ------------------------------------------------------------------
    # _assign_requests_to_connections tests
    # ------------------------------------------------------------------

    def test_assign_to_available_connection(self) -> None:
        """Existing connection with available streams gets assigned."""
        pool = self._make_pool()

        conn1 = self._make_mock_connection(
            is_available=True,
            is_idle=False,
            can_handle=True,
            max_conc_val=100,
        )
        pool._connections = [conn1]  # type: ignore[reportPrivateUsage]

        pool_req = self._make_mock_pool_request(queued=True)
        pool._requests = [pool_req]  # type: ignore[reportPrivateUsage]

        # Override create_connection to avoid real creation
        pool.create_connection = MagicMock()

        pool._assign_requests_to_connections()  # type: ignore[reportPrivateUsage]

        pool_req.assign_to_connection.assert_called_once_with(conn1)
        pool.create_connection.assert_not_called()

    def test_create_new_connection_when_full(self) -> None:
        """All connections full, pool has room → new connection created."""
        pool = self._make_pool(max_connections=10)

        conn1 = self._make_mock_connection(
            is_available=False,  # Not available (full)
            is_idle=False,
            can_handle=True,
        )
        pool._connections = [conn1]  # type: ignore[reportPrivateUsage]

        pool_req = self._make_mock_pool_request(queued=True)
        pool._requests = [pool_req]  # type: ignore[reportPrivateUsage]

        new_conn = self._make_mock_connection()
        pool.create_connection = MagicMock(return_value=new_conn)

        pool._assign_requests_to_connections()  # type: ignore[reportPrivateUsage]

        pool.create_connection.assert_called_once()
        pool_req.assign_to_connection.assert_called_once_with(new_conn)
        assert new_conn in pool._connections  # type: ignore[reportPrivateUsage]

    def test_close_idle_when_pool_full(self) -> None:
        """Pool at max capacity → close idle connection, create new one."""
        pool = self._make_pool(max_connections=1)

        conn1 = self._make_mock_connection(
            is_available=False,
            is_idle=True,
            can_handle=True,
        )
        pool._connections = [conn1]  # type: ignore[reportPrivateUsage]

        pool_req = self._make_mock_pool_request(queued=True)
        pool._requests = [pool_req]  # type: ignore[reportPrivateUsage]

        new_conn = self._make_mock_connection()
        pool.create_connection = MagicMock(return_value=new_conn)

        closing = pool._assign_requests_to_connections()  # type: ignore[reportPrivateUsage]

        pool.create_connection.assert_called_once()
        pool_req.assign_to_connection.assert_called_once_with(new_conn)
        assert conn1 in closing

    def test_connection_request_count_incremented(self) -> None:
        """Assignment increments per-connection request count."""
        pool = self._make_pool(max_connections=10)

        conn1 = self._make_mock_connection(
            is_available=True,
            is_idle=False,
            can_handle=True,
            max_conc_val=100,
        )
        pool._connections = [conn1]  # type: ignore[reportPrivateUsage]

        # Two queued requests
        pool_req1 = self._make_mock_pool_request(queued=True)
        pool_req2 = self._make_mock_pool_request(queued=True)
        pool._requests = [pool_req1, pool_req2]  # type: ignore[reportPrivateUsage]

        pool.create_connection = MagicMock()

        pool._assign_requests_to_connections()  # type: ignore[reportPrivateUsage]

        # Both should be assigned to conn1 since it has capacity
        assert pool_req1.assign_to_connection.called
        assert pool_req2.assign_to_connection.called

    def test_connection_request_count_initial_state(self) -> None:
        """Initial request count built from self._requests with assigned connections."""
        pool = self._make_pool(max_connections=10)

        conn1 = self._make_mock_connection(
            is_available=True,
            is_idle=False,
            can_handle=True,
            max_conc_val=100,
        )
        pool._connections = [conn1]  # type: ignore[reportPrivateUsage]

        # An already-assigned request on conn1
        assigned_req = self._make_mock_pool_request(queued=False, connection=conn1)
        # A queued request
        queued_req = self._make_mock_pool_request(queued=True)
        pool._requests = [assigned_req, queued_req]  # type: ignore[reportPrivateUsage]

        pool.create_connection = MagicMock()

        pool._assign_requests_to_connections()  # type: ignore[reportPrivateUsage]

        # The initial count for conn1 should be 1 (from assigned_req)
        # Then queued_req gets assigned
        queued_req.assign_to_connection.assert_called_once_with(conn1)

    # ------------------------------------------------------------------
    # _max_concurrent_requests tests
    # ------------------------------------------------------------------

    def test_max_concurrent_requests_supported(self) -> None:
        """Connection with max_concurrent_requests() returns its value."""
        pool = self._make_pool()
        conn = self._make_mock_connection(max_conc_val=200)

        result = pool._max_concurrent_requests(conn)  # type: ignore[reportPrivateUsage]
        assert result == 200

    def test_max_concurrent_requests_fallback(self) -> None:
        """Connection without max_concurrent_requests() returns 1."""
        pool = self._make_pool()
        conn = self._make_mock_connection(has_max_conc=False)

        result = pool._max_concurrent_requests(conn)  # type: ignore[reportPrivateUsage]
        assert result == 1

    # ------------------------------------------------------------------
    # create_connection tests
    # ------------------------------------------------------------------

    def test_create_connection_wires_callback(self) -> None:
        """create_connection() passes on_capacity_update callback."""
        pool = self._make_pool()

        origin = Origin(b"https", b"example.com", 443)
        # Patch CapacityAwareHTTPConnection in pool.py to capture constructor args
        with patch("src.core.http2.pool.CapacityAwareHTTPConnection") as mock_conn_cls:
            mock_conn_cls.return_value = MagicMock()
            pool.create_connection(origin)
            # Verify on_capacity_update was passed
            call_kwargs = mock_conn_cls.call_args.kwargs
            assert "on_capacity_update" in call_kwargs
            callback = call_kwargs["on_capacity_update"]
            # Bound methods are recreated on each access, so compare
            # by function identity and instance identity.
            cb_func = callback.__func__
            cb_self = callback.__self__
            tgt_func = CapacityAwareHttp2Pool._connection_capacity_updated  # type: ignore[reportPrivateUsage]
            assert cb_func is tgt_func
            assert cb_self is pool

    # ------------------------------------------------------------------
    # _connection_capacity_updated tests
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_capacity_updated_reassigns_requests(self) -> None:
        """_connection_capacity_updated() calls _assign_requests_to_connections."""
        pool = self._make_pool()

        mock_assign = MagicMock(return_value=[])
        pool._assign_requests_to_connections = mock_assign  # type: ignore[reportPrivateUsage]
        pool._close_connections = AsyncMock()  # type: ignore[reportPrivateUsage]

        await pool._connection_capacity_updated()  # type: ignore[reportPrivateUsage]

        mock_assign.assert_called_once()
        pool._close_connections.assert_called_once_with([])  # type: ignore[reportPrivateUsage]
