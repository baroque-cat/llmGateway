"""Unit tests for CapacityAwareHttp2Pool labels, cap, health summary, and logging.

Covers the h2-per-provider-stream-cap change: connection labels, per-connection
health breakdown, connection creation/closure logging, and cap-based new
connection opening.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from httpcore._async.http11 import AsyncHTTP11Connection
from httpcore._models import Origin

from src.core.http2.connection import CapacityAwareHTTPConnection
from src.core.http2.h2_connection import FixedHTTP2Connection
from src.core.http2.pool import CapacityAwareHttp2Pool


class TestCapacityAwareHttp2Pool:
    """Tests for connection labels, cap enforcement, health summary, and logging."""

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _make_pool(**kwargs: object) -> CapacityAwareHttp2Pool:
        """Create a CapacityAwareHttp2Pool with default settings.

        Args:
            **kwargs: Overrides for default pool settings.

        Returns:
            A pool instance with sensible defaults for unit tests.
        """
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
        """Create a mock connection for pool tests.

        Args:
            is_available: Return value for ``is_available()``.
            is_idle: Return value for ``is_idle()``.
            is_closed: Return value for ``is_closed()``.
            has_expired: Return value for ``has_expired()``.
            can_handle: Return value for ``can_handle_request()``.
            max_conc_val: Return value for ``max_concurrent_requests()``.
            has_max_conc: If False, delete ``max_concurrent_requests`` to
                simulate a connection without the method.

        Returns:
            A MagicMock simulating a pooled connection.
        """
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
        """Create a mock pool request for pool tests.

        Args:
            origin: The request origin (defaults to example.com:443).
            queued: Return value for ``is_queued()``.
            connection: The already-assigned connection (or None).

        Returns:
            A MagicMock simulating a pool request.
        """
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
    # Connection label tests
    # ------------------------------------------------------------------

    def test_connection_label_assigned_on_creation(self) -> None:
        """Connection label is assigned on creation with provider name and ordinal.

        The label follows the ``{provider_name}-conn-{ordinal}`` format,
        starting at ordinal 0.
        """
        pool = self._make_pool(provider_name="anthropic")
        origin = Origin(b"https", b"example.com", 443)

        conn = pool.create_connection(origin)

        assert isinstance(conn, CapacityAwareHTTPConnection)
        assert conn._connection_label == "anthropic-conn-0"  # type: ignore[reportPrivateUsage]

    def test_multiple_connections_sequential_labels(self) -> None:
        """Multiple connections get sequential ordinal labels.

        Each call to ``create_connection`` increments the ordinal counter,
        producing labels ``conn-0``, ``conn-1``, ``conn-2``, etc.
        """
        pool = self._make_pool(provider_name="deepseek")
        origin = Origin(b"https", b"example.com", 443)

        conn0 = pool.create_connection(origin)
        conn1 = pool.create_connection(origin)
        conn2 = pool.create_connection(origin)

        assert conn0._connection_label == "deepseek-conn-0"  # type: ignore[reportPrivateUsage]
        assert conn1._connection_label == "deepseek-conn-1"  # type: ignore[reportPrivateUsage]
        assert conn2._connection_label == "deepseek-conn-2"  # type: ignore[reportPrivateUsage]
        assert pool._connection_ordinal == 3  # type: ignore[reportPrivateUsage]

    def test_pool_label_assigned_on_creation(self) -> None:
        """Pool assigns a label to each connection on creation.

        Verifies that ``connection_label`` is passed through to the
        ``CapacityAwareHTTPConnection`` constructor.
        """
        pool = self._make_pool(provider_name="openai")
        origin = Origin(b"https", b"example.com", 443)

        with patch("src.core.http2.pool.CapacityAwareHTTPConnection") as mock_cls:
            mock_cls.return_value = MagicMock()
            pool.create_connection(origin)

            call_kwargs = mock_cls.call_args.kwargs
            assert call_kwargs["connection_label"] == "openai-conn-0"

    def test_pool_multiple_connections_sequential_labels(self) -> None:
        """Multiple connections created sequentially get sequential labels.

        The ordinal counter increments on each ``create_connection`` call,
        producing a monotonically increasing sequence of labels.
        """
        pool = self._make_pool()
        origin = Origin(b"https", b"example.com", 443)

        with patch("src.core.http2.pool.CapacityAwareHTTPConnection") as mock_cls:
            mock_cls.return_value = MagicMock()
            pool.create_connection(origin)
            pool.create_connection(origin)
            pool.create_connection(origin)

            labels = [
                call.kwargs["connection_label"] for call in mock_cls.call_args_list
            ]
            assert labels == ["unknown-conn-0", "unknown-conn-1", "unknown-conn-2"]

    # ------------------------------------------------------------------
    # Cap forces new connection test
    # ------------------------------------------------------------------

    def test_cap_forces_new_connection_before_server_limit(self) -> None:
        """Cap forces a new connection before the server-advertised stream limit.

        When ``max_concurrent_streams_cap=3`` and 4 requests arrive, the 4th
        request cannot fit in the first connection (capped at 3 streams) and
        forces the pool to open a second connection — even though the server
        might advertise a higher limit.
        """
        pool = self._make_pool(
            max_concurrent_streams_cap=3,
            max_connections=10,
        )

        # Simulate a connection whose effective capacity is the cap (3),
        # not the server-advertised value (which would be higher).
        conn1 = self._make_mock_connection(
            is_available=True,
            is_idle=False,
            can_handle=True,
            max_conc_val=3,
        )
        conn1._connection_label = "unknown-conn-0"
        pool._connections = [conn1]  # type: ignore[reportPrivateUsage]

        requests = [self._make_mock_pool_request(queued=True) for _ in range(4)]
        pool._requests = requests  # type: ignore[reportPrivateUsage]

        new_conn = self._make_mock_connection(max_conc_val=3)
        pool.create_connection = MagicMock(return_value=new_conn)

        pool._assign_requests_to_connections()  # type: ignore[reportPrivateUsage]

        # First 3 requests assigned to conn1 (within cap).
        for i in range(3):
            requests[i].assign_to_connection.assert_called_once_with(conn1)
        # 4th request forced a new connection.
        pool.create_connection.assert_called_once()
        requests[3].assign_to_connection.assert_called_once_with(new_conn)
        assert new_conn in pool._connections  # type: ignore[reportPrivateUsage]

    # ------------------------------------------------------------------
    # Health summary tests
    # ------------------------------------------------------------------

    def test_health_summary_per_connection_details(self) -> None:
        """Per-connection details include label, state, protocol, active_streams, max_streams.

        Each entry in the ``connections`` list is a dict with all five keys
        and values of the correct type.
        """
        pool = self._make_pool()

        h2_inner = object.__new__(FixedHTTP2Connection)
        h2_conn = self._make_mock_connection(is_idle=False, max_conc_val=100)
        h2_conn._connection = h2_inner
        h2_conn._connection_label = "anthropic-conn-0"

        h1_inner = object.__new__(AsyncHTTP11Connection)
        h1_conn = self._make_mock_connection(is_idle=True, max_conc_val=1)
        h1_conn._connection = h1_inner
        h1_conn._connection_label = "anthropic-conn-1"

        pool._connections = [h2_conn, h1_conn]  # type: ignore[reportPrivateUsage]
        pool._requests = []  # type: ignore[reportPrivateUsage]

        summary = pool.get_health_summary()

        connections = summary["connections"]
        assert isinstance(connections, list)
        assert len(connections) == 2

        for detail in connections:
            assert "label" in detail
            assert "state" in detail
            assert "protocol" in detail
            assert "active_streams" in detail
            assert "max_streams" in detail
            assert isinstance(detail["label"], str)
            assert isinstance(detail["state"], str)
            assert isinstance(detail["protocol"], str)
            assert isinstance(detail["active_streams"], int)
            assert isinstance(detail["max_streams"], int)

        h2_detail = connections[0]
        assert h2_detail["label"] == "anthropic-conn-0"
        assert h2_detail["state"] == "active"
        assert h2_detail["protocol"] == "h2"
        assert h2_detail["max_streams"] == 100

        h1_detail = connections[1]
        assert h1_detail["label"] == "anthropic-conn-1"
        assert h1_detail["state"] == "idle"
        assert h1_detail["protocol"] == "h1"

    def test_health_summary_empty_connections_list(self) -> None:
        """Empty pool returns an empty connections list.

        When no connections exist, ``get_health_summary()`` returns
        ``connections: []`` and ``total_connections: 0``.
        """
        pool = self._make_pool()
        pool._connections = []  # type: ignore[reportPrivateUsage]
        pool._requests = []  # type: ignore[reportPrivateUsage]

        summary = pool.get_health_summary()

        assert summary["connections"] == []
        assert isinstance(summary["connections"], list)
        assert summary["total_connections"] == 0

    def test_health_summary_returns_per_connection_breakdown(self) -> None:
        """Health summary returns a per-connection breakdown list.

        The ``connections`` key contains one entry per pooled connection,
        each carrying the connection's label.
        """
        pool = self._make_pool()

        conn1 = self._make_mock_connection(is_idle=False, max_conc_val=50)
        conn1._connection_label = "a-conn-0"
        conn2 = self._make_mock_connection(is_idle=True, max_conc_val=50)
        conn2._connection_label = "a-conn-1"

        pool._connections = [conn1, conn2]  # type: ignore[reportPrivateUsage]
        pool._requests = []  # type: ignore[reportPrivateUsage]

        summary = pool.get_health_summary()

        assert "connections" in summary
        breakdown = summary["connections"]
        assert len(breakdown) == 2
        assert breakdown[0]["label"] == "a-conn-0"
        assert breakdown[1]["label"] == "a-conn-1"

    # ------------------------------------------------------------------
    # Logging tests
    # ------------------------------------------------------------------

    def test_connection_creation_logged(self) -> None:
        """Connection creation is logged at INFO with the connection label.

        ``create_connection`` emits an INFO log containing "Creating connection"
        and the generated label.
        """
        pool = self._make_pool(provider_name="anthropic")
        origin = Origin(b"https", b"example.com", 443)

        with patch("src.core.http2.pool.logger") as mock_logger:
            pool.create_connection(origin)

        mock_logger.info.assert_called_once()
        log_msg = mock_logger.info.call_args[0][0]
        assert "Creating connection" in log_msg
        assert "anthropic-conn-0" in log_msg

    def test_connection_closure_logged(self) -> None:
        """Connection closure is logged at INFO during cleanup.

        When a connection is expired (but not closed), the pool logs
        "Closing connection" with the connection's label during the
        cleanup phase of ``_assign_requests_to_connections``.
        """
        pool = self._make_pool(max_keepalive_connections=5)

        expired_conn = self._make_mock_connection(
            is_closed=False,
            has_expired=True,
            is_idle=False,
        )
        expired_conn._connection_label = "test-conn-5"
        pool._connections = [expired_conn]  # type: ignore[reportPrivateUsage]
        pool._requests = []  # type: ignore[reportPrivateUsage]

        with patch("src.core.http2.pool.logger") as mock_logger:
            pool._assign_requests_to_connections()  # type: ignore[reportPrivateUsage]

        mock_logger.info.assert_called_once()
        log_msg = mock_logger.info.call_args[0][0]
        assert "Closing connection" in log_msg
        assert "test-conn-5" in log_msg
