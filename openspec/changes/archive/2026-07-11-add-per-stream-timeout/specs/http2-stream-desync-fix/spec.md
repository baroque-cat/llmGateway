## ADDED Requirements

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

## MODIFIED Requirements

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
