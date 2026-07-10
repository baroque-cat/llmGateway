# http2-stream-desync-fix

Fix for the stream desync bug in httpcore's `AsyncHTTP2Connection` where asyncio task cancellation causes phantom stream accumulation in h2's state, leading to `NoAvailableStreamIDError` → `LocalProtocolError` cascades.

## Requirements

### Requirement: Connection cleans up h2 stream state after asyncio cancellation

`FixedHTTP2Connection._response_closed()` SHALL synchronize the h2 library's stream state with httpcore's semaphore after asyncio task cancellation.

#### Scenario: Normal stream close (no cancellation)

- **WHEN** `_response_closed(stream_id)` is called and the stream was cleanly closed by the server (stream_id is in `_closed_streams`)
- **THEN** no `reset_stream()` is called, the semaphore is released (if capacity allows), and `_closed_streams` entry is discarded

#### Scenario: Cancelled stream (stream not in _closed_streams)

- **WHEN** `_response_closed(stream_id)` is called and `stream_id` is NOT in `_closed_streams` (stream was cancelled before server response)
- **THEN** `h2_state.reset_stream(stream_id)` is called, errors (`NoSuchStreamError`, `ProtocolError`) are silently caught, and the semaphore is released conditionally

#### Scenario: Semaphore release is conditional

- **WHEN** `_response_closed(stream_id)` releases the semaphore
- **THEN** the release only occurs if `len(self._events) <= self._max_streams` to prevent semaphore overflow

#### Scenario: Connection closes when stream was reset

- **WHEN** `_response_closed` completes for a `stream_was_reset` stream and no more events are active
- **THEN** the connection is closed via `aclose()` instead of transitioning to IDLE, preventing inconsistent state

### Requirement: Connection tracks server-closed streams

`FixedHTTP2Connection` SHALL maintain a `_closed_streams: set[int]` to track streams that the server cleanly closed (via `StreamEnded` or `StreamReset` events).

#### Scenario: Server closes stream cleanly

- **WHEN** `_receive_events()` processes a `h2.events.StreamEnded` or `h2.events.StreamReset` event for an active stream
- **THEN** the event's `stream_id` is added to `self._closed_streams`

### Requirement: Connection advertises H2 stream capacity

`FixedHTTP2Connection.is_available()` SHALL return `False` when all H2 streams are occupied, in addition to existing checks (CLOSED state, connection errors, exhausted stream IDs).

#### Scenario: Connection is full

- **WHEN** `is_available()` is called and `len(self._events) >= self.max_concurrent_requests()`
- **THEN** the method returns `False`, preventing the pool from assigning new requests

#### Scenario: Connection has room

- **WHEN** `is_available()` is called and `len(self._events) < self.max_concurrent_requests()` and all other checks pass
- **THEN** the method returns `True`

### Requirement: Connection signals pool on SETTINGS change

`FixedHTTP2Connection._receive_remote_settings_change()` SHALL call `self._on_capacity_update()` callback after adjusting the semaphore when the server changes `SETTINGS_MAX_CONCURRENT_STREAMS`.

#### Scenario: Server increases stream limit

- **WHEN** `_receive_remote_settings_change()` processes a new `SETTINGS_MAX_CONCURRENT_STREAMS` value higher than current
- **THEN** the semaphore is released for the new slots, `_max_streams` is updated, and `_on_capacity_update()` is called if set

#### Scenario: No callback configured

- **WHEN** `_on_capacity_update` is `None`
- **THEN** no callback is called, semaphore adjustment proceeds normally

### Requirement: Connection returns max concurrent requests

`FixedHTTP2Connection.max_concurrent_requests()` SHALL return the number of streams this connection can handle concurrently.

#### Scenario: Connection initialized

- **WHEN** `max_concurrent_requests()` is called after `_sent_connection_init` is `True`
- **THEN** the method returns `self._max_streams`

#### Scenario: Connection not yet initialized

- **WHEN** `max_concurrent_requests()` is called before `_sent_connection_init` is `True`
- **THEN** the method returns `1`

### Requirement: Per-stream response header deadline
`FixedHTTP2Connection.handle_async_request()` SHALL enforce a per-stream deadline on
the response header wait phase by wrapping `_receive_response()` in
`asyncio.wait_for()`.  The timeout value SHALL be taken from
`request.extensions["stream_read"]` when present and not ``None``.
When ``stream_read`` is ``None`` or absent, no per-stream deadline SHALL be
enforced — ``_receive_response()`` SHALL be called directly, preserving the
original socket-level ``read`` timeout behavior.

#### Scenario: Per-stream timeout fires for starved stream
- **WHEN** a stream's `_receive_response` call has not returned within the
  timeout period (e.g., 120s), and other streams on the same connection are
  receiving data
- **THEN** `asyncio.wait_for` SHALL raise `TimeoutError`
- **AND** the handler SHALL send `RST_STREAM` for the timed-out stream
- **AND** `_response_closed` SHALL be called, releasing the semaphore slot
- **AND** `_events[stream_id]` SHALL be removed
- **AND** the connection and other streams SHALL remain operational

#### Scenario: Per-stream timeout does not fire for fast response
- **WHEN** a stream's `_receive_response` returns headers within the timeout
  period (e.g., 0.5s)
- **THEN** `asyncio.wait_for` SHALL return normally
- **AND** the response SHALL be returned to the caller

#### Scenario: stream_read overrides read
- **WHEN** `request.extensions["stream_read"]` is set to `30.0` and
  `request.extensions["timeout"]["read"]` is `120.0`
- **THEN** the per-stream timeout SHALL use `30.0`
- **AND** `asyncio.wait_for` SHALL fire after approximately 30s

#### Scenario: stream_read is None — no per-stream deadline
- **WHEN** `request.extensions["stream_read"]` is `None`
- **THEN** no per-stream deadline SHALL be enforced — ``_receive_response()`` SHALL be called directly without ``asyncio.wait_for``
- **AND** the socket-level ``read`` timeout SHALL remain as the only backstop

#### Scenario: RST_STREAM sent before semaphore release
- **WHEN** `TimeoutError` is caught from `asyncio.wait_for`
- **THEN** `self._h2_state.reset_stream(stream_id)` SHALL be called
- **AND** `await self._write_outgoing_data(request)` SHALL be called
- **AND** the `TimeoutError` SHALL then be re-raised to the outer `except BaseException`

### Requirement: handle_async_request wraps _receive_response in asyncio.wait_for
The `handle_async_request` method in `FixedHTTP2Connection` SHALL wrap the
`_receive_response` call (the header-wait phase) in `asyncio.wait_for()` **only
when `request.extensions["stream_read"]` is a non-``None`` value**.
This is a per-stream deadline enforced at the Python event-loop level,
unaffected by socket activity from other streams.

When ``stream_read`` is ``None`` (the default), ``_receive_response`` SHALL be
called directly — the socket-level ``read`` timeout remains as the backstop.

The inner ``except TimeoutError`` handler SHALL convert the raw
``TimeoutError`` from ``asyncio.wait_for`` into an ``httpcore.ReadTimeout``
before re-raising, so httpx maps it to ``httpx.ReadTimeout`` (a subclass of
``httpx.RequestError`` caught by the provider's error handling).

The existing `except BaseException` → `_response_closed` cleanup path SHALL
handle ``httpcore.ReadTimeout`` from the per-stream deadline identically to any other
exception — releasing the semaphore, cleaning up `_events`, and transitioning
connection state.

The `_send_request_headers` and `_send_request_body` calls SHALL remain
outside the `asyncio.wait_for` wrapper — only the header-wait phase is covered.
