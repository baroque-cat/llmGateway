"""Ephemeral HTTP/2 server for connection pool stress tests.

Provides a minimal, configurable HTTP/2-over-TLS server built on asyncio + h2.
Designed for controlled reproduction of httpx connection pool behavior
under constrained stream limits, response delays, and connection counts.

The server generates a self-signed certificate at startup so that httpx can
negotiate HTTP/2 via TLS (h2). No external dependencies beyond asyncio, h2,
and ssl (all stdlib or transitive deps of httpx[http2]).
"""

from __future__ import annotations

import asyncio
import contextlib
import ssl
from pathlib import Path

import h2.config
import h2.connection
import h2.events
import h2.settings

_CERT_DIR = Path(__file__).resolve().parent
_CERT_FILE = _CERT_DIR / "cert.pem"
_KEY_FILE = _CERT_DIR / "key.pem"


class EphemeralHttp2Server:
    """A minimal HTTP/2-over-TLS server for stress-testing httpx connection pools.

    Starts on a random available port, advertises configurable
    ``SETTINGS_MAX_CONCURRENT_STREAMS``, and exposes real-time connection/stream
    counters via :attr:`stats`. Uses a self-signed certificate from
    ``tests/stress/cert.pem`` / ``tests/stress/key.pem``.

    Fields:
        host: Bind address (default ``"127.0.0.1"``).
        port: Bind port (0 = OS-assigned).
        max_concurrent_streams: Advertised via HTTP/2 SETTINGS.
        response_delay_ms: Artificial delay before each response.
        response_status: HTTP status code to return.
        response_body: Raw body bytes to return.
    """

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 0,
        max_concurrent_streams: int = 100,
        response_delay_ms: int = 0,
        response_status: int = 200,
        response_body: bytes = b'{"ok":true}',
    ) -> None:
        self._host = host
        self._port = port
        self._max_concurrent_streams = max_concurrent_streams
        self._response_delay_ms = response_delay_ms
        self._response_status = response_status
        self._response_body = response_body

        self._server: asyncio.AbstractServer | None = None
        self._actual_port: int = 0
        self._lock = asyncio.Lock()

        # Connection lifecycle counters
        self._active_connections: int = 0
        self._total_connections: int = 0
        self._peak_connections: int = 0

        # Stream counters
        self._active_streams: int = 0
        self._peak_concurrent_streams: int = 0

        # Request/error counters
        self._total_requests: int = 0
        self._errors: int = 0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def url(self) -> str:
        """Return the server's HTTPS URL after :meth:`start` has been called."""
        return f"https://{self._host}:{self._actual_port}"

    @property
    def stats(self) -> dict[str, int]:
        """Return a snapshot of the server's internal counters.

        Keys:
            ``active_connections`` — currently-open TCP connections.
            ``total_connections`` — total connections opened (cumulative).
            ``peak_connections`` — highest ``active_connections`` observed.
            ``active_streams`` — currently-open HTTP/2 streams.
            ``peak_concurrent_streams`` — highest ``active_streams`` observed.
            ``total_requests`` — total requests handled (cumulative).
            ``errors`` — total stream-reset or unexpected protocol errors.
        """
        return {
            "active_connections": self._active_connections,
            "total_connections": self._total_connections,
            "peak_connections": self._peak_connections,
            "active_streams": self._active_streams,
            "peak_concurrent_streams": self._peak_concurrent_streams,
            "total_requests": self._total_requests,
            "errors": self._errors,
        }

    async def start(self) -> str:
        """Start the server and return its HTTPS URL.

        Creates a TLS context from the pre-generated self-signed certificate,
        binds to ``host:port``, and begins accepting connections.

        Returns:
            The server's URL, e.g. ``"https://127.0.0.1:45678"``.
        """
        ssl_context = _create_ssl_context()
        self._server = await asyncio.start_server(
            self._handle_connection,
            host=self._host,
            port=self._port,
            ssl=ssl_context,
        )
        for sock in self._server.sockets:
            sockname = sock.getsockname()
            self._actual_port = sockname[1]
            break
        return self.url

    async def stop(self) -> None:
        """Shut down the server, wait for pending connections, release the port."""
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None

    def set_delay(self, delay_ms: int) -> None:
        """Change the response delay for subsequent requests."""
        self._response_delay_ms = delay_ms

    def set_status(self, status: int) -> None:
        """Change the HTTP status code for subsequent requests."""
        self._response_status = status

    def reset_metrics(self) -> None:
        """Reset all internal counters to zero."""
        self._active_connections = 0
        self._total_connections = 0
        self._peak_connections = 0
        self._active_streams = 0
        self._peak_concurrent_streams = 0
        self._total_requests = 0
        self._errors = 0

    # ------------------------------------------------------------------
    # Internal: connection / request handling
    # ------------------------------------------------------------------

    async def _handle_connection(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        """Handle a single TLS-wrapped TCP connection using the h2 protocol."""
        async with self._lock:
            self._active_connections += 1
            self._total_connections += 1
            if self._active_connections > self._peak_connections:
                self._peak_connections = self._active_connections

        config = h2.config.H2Configuration(client_side=False, header_encoding="utf-8")
        conn = h2.connection.H2Connection(config=config)
        conn.initiate_connection()
        conn.update_settings(
            {
                h2.settings.SettingCodes.MAX_CONCURRENT_STREAMS: (
                    self._max_concurrent_streams
                ),
            }
        )

        # Per-connection lock serialises writes to the h2 connection object
        # and the transport so that concurrent _handle_request tasks do not
        # interleave frames on the wire.
        conn_lock = asyncio.Lock()
        pending_tasks: set[asyncio.Task[None]] = set()

        try:
            # Send server preface + SETTINGS frame immediately
            initial_data = conn.data_to_send()
            if initial_data:
                writer.write(initial_data)
                await writer.drain()

            while True:
                data = await reader.read(65536)
                if not data:
                    break

                events = conn.receive_data(data)

                for event in events:
                    if isinstance(event, h2.events.RequestReceived):
                        async with self._lock:
                            self._active_streams += 1
                            self._total_requests += 1
                            if self._active_streams > self._peak_concurrent_streams:
                                self._peak_concurrent_streams = self._active_streams
                        task = asyncio.create_task(
                            self._handle_request(conn, event, conn_lock, writer)
                        )
                        pending_tasks.add(task)
                        task.add_done_callback(pending_tasks.discard)
                    elif isinstance(event, h2.events.StreamEnded):
                        pass  # handled in _handle_request after response
                    elif isinstance(event, h2.events.StreamReset):
                        async with self._lock:
                            self._errors += 1
                            self._active_streams = max(0, self._active_streams - 1)
                    elif isinstance(event, h2.events.ConnectionTerminated):
                        # Client sent GOAWAY — stop reading
                        return
                    elif isinstance(event, h2.events.DataReceived):
                        # Acknowledge received data for flow control
                        conn.acknowledge_received_data(
                            event.flow_controlled_length, event.stream_id
                        )
                    elif isinstance(event, h2.events.PingReceived) and not getattr(
                        event, "ping_ack", False
                    ):
                        # Respond to non-ACK PINGs
                        conn.ping(event.ping_data)
                    # Ignore: RemoteSettingsChanged, WindowUpdated,
                    # PriorityUpdated, SettingsAcknowledged, etc.

                # Flush any frames queued by the main event loop (e.g. PING
                # acks, SETTINGS acks).  Response frames are flushed inside
                # _handle_request under conn_lock.
                async with conn_lock:
                    outgoing = conn.data_to_send()
                if outgoing:
                    writer.write(outgoing)
                    await writer.drain()

        except Exception:
            async with self._lock:
                self._errors += 1
        finally:
            # Wait for any in-flight request tasks to finish before closing.
            if pending_tasks:
                await asyncio.gather(*pending_tasks, return_exceptions=True)
            with contextlib.suppress(Exception):
                writer.close()
            async with self._lock:
                self._active_connections = max(0, self._active_connections - 1)

    async def _handle_request(
        self,
        conn: h2.connection.H2Connection,
        event: h2.events.RequestReceived,
        conn_lock: asyncio.Lock,
        writer: asyncio.StreamWriter,
    ) -> None:
        """Process one HTTP/2 request: apply delay, send response, track metrics."""
        if self._response_delay_ms > 0:
            await asyncio.sleep(self._response_delay_ms / 1000.0)

        response_headers = [
            (":status", str(self._response_status)),
            ("content-type", "application/json"),
            ("content-length", str(len(self._response_body))),
            ("server", "EphemeralHttp2Server"),
        ]

        async with conn_lock:
            try:
                conn.send_headers(event.stream_id, response_headers)
                conn.send_data(event.stream_id, self._response_body, end_stream=True)
            except Exception:
                async with self._lock:
                    self._errors += 1
                return

            outgoing = conn.data_to_send()

        if outgoing:
            writer.write(outgoing)
            await writer.drain()

        async with self._lock:
            self._active_streams = max(0, self._active_streams - 1)


# ------------------------------------------------------------------
# Internal helpers
# ------------------------------------------------------------------


def _create_ssl_context() -> ssl.SSLContext:
    """Create an SSL context using the pre-generated self-signed certificate."""
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(str(_CERT_FILE), str(_KEY_FILE))
    # Allow older TLS versions for maximum client compatibility in tests
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    # Advertise HTTP/2 via ALPN so httpx can negotiate h2
    ctx.set_alpn_protocols(["h2"])
    return ctx
