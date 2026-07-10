## ADDED Requirements

### Requirement: FixedHTTP2Connection enforces per-stream deadline from config
`FixedHTTP2Connection.handle_async_request()` SHALL read a per-stream timeout
value from `request.extensions["stream_read"]`.  When set to a non-``None``
value, it SHALL enforce the deadline via ``asyncio.wait_for()`` wrapping the
``_receive_response()`` call.  When ``None``, no per-stream deadline SHALL be
enforced — the socket-level ``read`` timeout SHALL remain as the only backstop.

#### Scenario: Deadline fires, semaphore released, connection survives
- **WHEN** a stream's response headers do not arrive within the deadline
- **THEN** `TimeoutError` SHALL be raised
- **AND** a `RST_STREAM` frame SHALL be sent on the H2 connection
- **AND** `_response_closed()` SHALL release the semaphore slot
- **AND** `_events[stream_id]` SHALL be deleted
- **AND** other streams on the same connection SHALL continue unaffected

#### Scenario: Deadline does not fire for normal response
- **WHEN** response headers arrive well within the deadline
- **THEN** `asyncio.wait_for()` SHALL return the status and headers normally
- **AND** the response SHALL be returned to the caller

#### Scenario: stream_read from config takes priority over read
- **WHEN** the provider config has `timeouts.stream_read: 300` and `timeouts.read: 120`
- **THEN** `request.extensions["stream_read"]` SHALL be `300.0`
- **AND** the per-stream deadline SHALL be 300s

#### Scenario: Default behavior when stream_read is not configured
- **WHEN** the provider config has `timeouts.read: 120` and no `stream_read`
- **THEN** `request.extensions["stream_read"]` SHALL be `None`
- **AND** no per-stream deadline SHALL be enforced — the socket-level ``read`` timeout SHALL remain as the only backstop, preserving the original behavior where active streams keep the socket busy and a starved stream does NOT time out
