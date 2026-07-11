# Per-Stream Timeout Logging

## Purpose

Observability for the per-stream response header deadline in the HTTP/2 transport:
emit an `INFO`-level log at the transport layer when the deadline fires, and
disambiguate the provider-level `ReadTimeout` error detail between per-stream
deadline exhaustion (`stream_read=Xs`) and socket-level timeout
(`read_timeout=Xs`).

## Requirements

### Requirement: Per-stream timeout logged at transport layer
`FixedHTTP2Connection.handle_async_request()` SHALL emit an `INFO`-level log
message when the per-stream deadline fires, before the `ReadTimeout` exception
is raised. The message SHALL include the `stream_id` and the `stream_read`
value that expired.

#### Scenario: Log emitted on per-stream timeout
- **WHEN** `asyncio.wait_for` raises `TimeoutError` in the inner exception
  handler
- **THEN** a log message SHALL be emitted at `INFO` level containing
  `"Per-stream response timeout"`, the `stream_id` of the timed-out stream,
  and the `stream_read` timeout value in seconds
- **AND** the log message SHALL be emitted before `ReadTimeout` is raised

#### Scenario: No log when per-stream deadline is not configured
- **WHEN** `request.extensions["stream_read"]` is `None`
- **THEN** no per-stream timeout log SHALL be emitted (the code path does not
  enter the `asyncio.wait_for` block)

### Requirement: Provider error detail distinguishes per-stream from socket timeout
The `_send_proxy_request` error handler in `AIBaseProvider` SHALL distinguish
between a per-stream deadline exhaustion and a socket-level read timeout when
logging `httpx.ReadTimeout` exceptions.

#### Scenario: Per-stream deadline identified in error detail
- **WHEN** `httpx.ReadTimeout` is caught and the exception message contains
  `"Per-stream timeout"`
- **THEN** the error detail string SHALL report `stream_read=Xs` (the
  configured per-stream deadline value) instead of `read_timeout=Xs`

#### Scenario: Socket-level timeout reported when per-stream not involved
- **WHEN** `httpx.ReadTimeout` is caught and the exception message does NOT
  contain `"Per-stream timeout"`
- **THEN** the error detail string SHALL continue to report
  `read_timeout=Xs` as before (backward compatible)
