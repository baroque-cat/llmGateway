## ADDED Requirements

### Requirement: EphemeralHttp2Server lifecycle
The system SHALL provide an `EphemeralHttp2Server` class that starts an HTTP/2 server on a random available port, serves configurable responses, and exposes connection/stream metrics.

#### Scenario: Server starts on random port
- **WHEN** `server = EphemeralHttp2Server(max_concurrent_streams=100)` and `await server.start()` is called
- **THEN** the server SHALL bind to `127.0.0.1` on a port assigned by the OS (`port=0`)
- **THEN** `server.url` SHALL return `"https://127.0.0.1:<assigned_port>"`
- **THEN** `server.stats["active_connections"]` SHALL be `0`

#### Scenario: Server responds to single HTTP/2 request
- **WHEN** an `httpx.AsyncClient(http2=True)` sends `GET <server.url>/test`
- **THEN** the server SHALL respond with HTTP status 200 and body `{"ok":true}`
- **THEN** `server.stats["total_requests"]` SHALL be `1`

#### Scenario: Server stops cleanly
- **WHEN** `await server.stop()` is called
- **THEN** all active connections SHALL be closed
- **THEN** the listening socket SHALL be released

### Requirement: Configurable SETTINGS_MAX_CONCURRENT_STREAMS
The `EphemeralHttp2Server` SHALL accept a `max_concurrent_streams` parameter and advertise it via the HTTP/2 SETTINGS frame during connection handshake.

#### Scenario: Client observes the stream limit
- **WHEN** a server is created with `max_concurrent_streams=5`
- **THEN** the server SHALL send `SETTINGS_MAX_CONCURRENT_STREAMS=5` in its initial SETTINGS frame
- **THEN** an HTTP/2 client connected to this server SHALL not open more than 5 concurrent streams per connection without receiving a `REFUSED_STREAM` or `ENHANCE_YOUR_CALM` error
- **THEN** the client MAY open additional TCP connections to handle more than 5 concurrent requests

### Requirement: Configurable response delay
The `EphemeralHttp2Server` SHALL support a `response_delay_ms` parameter that introduces a controlled delay before responding to each request, simulating slow upstream behavior.

#### Scenario: Response arrives after configured delay
- **WHEN** server is created with `response_delay_ms=500`
- **WHEN** a client sends a request at time `T0`
- **THEN** the response SHALL arrive no earlier than `T0 + 500ms`
- **THEN** `server.stats["active_streams"]` SHALL be `1` during the delay period

### Requirement: Connection and stream counters
The `EphemeralHttp2Server` SHALL track and expose per-connection and aggregate metrics via a `stats` property.

#### Scenario: Metrics reflect concurrent state
- **WHEN** 3 TCP connections are established and their requests have completed
- **THEN** `stats["active_connections"]` SHALL be `3` and `stats["active_streams"]` SHALL be `0`

#### Scenario: Peak stream count is tracked
- **WHEN** 10 concurrent requests arrive, each on a separate TCP connection
- **THEN** `stats["peak_concurrent_streams"]` SHALL be at least `10`

#### Scenario: Total connection count is cumulative
- **WHEN** 3 connections are opened, then 2 are closed, then 1 more is opened
- **THEN** `stats["total_connections"]` SHALL be `4`

### Requirement: MetricsCollector aggregates from multiple sources
The `MetricsCollector` SHALL collect connection lifecycle metrics from the ephemeral server's counters and from httpx trace events, producing a `ConnectionMetrics` dataclass.

#### Scenario: httpx trace captures connection creation
- **WHEN** an `httpx.AsyncClient` is created with `extensions={"trace": collector.trace_handler}`
- **WHEN** the client sends requests that cause httpx to open a new connection
- **THEN** `collector.stop().client_connections_created` SHALL be at least `1`

#### Scenario: Error classification by exception type
- **WHEN** 5 out of 20 requests fail with `httpx.LocalProtocolError`
- **WHEN** 3 fail with `httpx.PoolTimeout`
- **WHEN** the remaining 12 succeed
- **THEN** `collector.stop().local_protocol_errors` SHALL be `5`
- **THEN** `collector.stop().pool_timeout_errors` SHALL be `3`

#### Scenario: OS TCP metric is optional
- **WHEN** `MetricsCollector` is created on a platform without `/proc/net/tcp` (e.g., macOS or Windows)
- **THEN** `collector.stop().os_tcp_established` SHALL be `None` (not an error)
