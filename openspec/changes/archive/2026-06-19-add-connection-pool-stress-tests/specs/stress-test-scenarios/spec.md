## ADDED Requirements

### Requirement: Stream exhaustion reproduces LocalProtocolError
The system SHALL have a test (Test 1) that reproduces `httpx.LocalProtocolError` ("Max outbound streams") under controlled conditions: a single allowed connection with a stream limit lower than the request count.

#### Scenario: Requests exceed stream limit on single connection
- **WHEN** `EphemeralHttp2Server` is configured with `max_concurrent_streams=5` and `response_delay_ms=2000`
- **WHEN** `httpx.AsyncClient` is created with `max_connections=1`, `max_keepalive_connections=1`
- **WHEN** 20 concurrent GET requests are sent
- **THEN** at most 5 requests SHALL succeed (the number matching `max_concurrent_streams`)
- **THEN** the remaining 15 requests SHALL fail with either `httpx.LocalProtocolError` or `httpx.PoolTimeout`
- **THEN** `MetricsCollector` SHALL report `local_protocol_errors > 0` or `pool_timeout_errors > 0`

### Requirement: httpx opens new connections when streams are exhausted
The system SHALL have a test (Test 2) that diagnoses whether httpx opens additional TCP connections when H2 streams on existing connections reach the server-advertised limit, within `max_connections`.

#### Scenario: Six connections needed for 30 requests with 5-stream limit
- **WHEN** `EphemeralHttp2Server` is configured with `max_concurrent_streams=5` and `response_delay_ms=2000`
- **WHEN** `httpx.AsyncClient` is created with `max_connections=10`, `max_keepalive_connections=10`, `keepalive_expiry=30.0`
- **WHEN** 30 concurrent GET requests are sent
- **THEN** under current httpx behavior, only `max_concurrent_streams` requests SHALL succeed (5 of 30)
- **THEN** the remaining 25 requests SHALL fail with `httpx.LocalProtocolError`
- **THEN** `MetricsCollector.client_connections_created` SHALL be `1` (httpx does not open additional connections)
- **THEN** this test is marked `pytest.mark.xfail(strict=True)` to document that httpx does NOT open new connections when H2 streams are exhausted

### Requirement: Pool saturation produces distinguishable error type
The system SHALL have a test (Test 3) that verifies the error type produced when the connection pool is saturated with long-running requests, distinguishing connection-level errors from stream-level errors.

#### Scenario: Pool exhausted with long responses
- **WHEN** `EphemeralHttp2Server` is configured with `response_delay_ms=10000` (10 seconds) and `max_concurrent_streams=1`
- **WHEN** `httpx.AsyncClient` is created with `max_connections=3`, `pool_timeout=5.0` (in httpx.Timeout)
- **WHEN** 20 concurrent GET requests are sent
- **THEN** at most 3 requests SHALL succeed (one per connection)
- **THEN** under HTTP/2, the remaining 17 requests SHALL fail with `httpx.LocalProtocolError` rather than `httpx.PoolTimeout`, because httpx sends multiple streams to existing connections instead of queuing for pool slots
- **THEN** `MetricsCollector.local_protocol_errors` SHALL be greater than `0`
- **THEN** this test is marked `pytest.mark.xfail(strict=True)` to document that HTTP/2 multiplexing prevents genuine pool-timeout behavior

### Requirement: Short keep-alive expiry causes connection churn
The system SHALL have a test (Test 4) that measures connection creation frequency when `keepalive_expiry` is set to a low value, demonstrating that connections are recreated unnecessarily.

#### Scenario: Connections expire between sequential requests
- **WHEN** `httpx.AsyncClient` is created with `keepalive_expiry=5.0` and `max_keepalive_connections=20`
- **WHEN** 20 sequential (non-concurrent) GET requests are sent with a 6-second gap between each
- **THEN** `MetricsCollector.client_connections_created` SHALL be at least `10` (approximately one new connection per 2 requests, since the first expires before the third)

### Requirement: Recovery after connection pool overload
The system SHALL have a test (Test 6) that verifies the connection pool recovers after a load spike subsides, without permanent connection leaks.

#### Scenario: Pool recovers after load reduction
- **WHEN** Phase 1: 50 concurrent requests are sent (some expected to fail due to limits)
- **WHEN** Phase 2: After a 30-second quiet period, 5 concurrent requests are sent
- **THEN** Phase 2 SHALL have 5 successful responses
- **THEN** `server.stats["active_connections"]` SHALL return to 0 or 1 after the quiet period

### Requirement: Multiple independent clients do not share pools
The system SHALL have a test (Test 5) that verifies multiple independently-created `httpx.AsyncClient` instances (simulating multi-worker behavior) each maintain their own connection pool.

#### Scenario: Two clients create independent connections
- **WHEN** Two separate `httpx.AsyncClient` instances are created with `max_connections=5` and `dedicated_http_client` semantics
- **WHEN** Each client sends 10 concurrent requests
- **THEN** `server.stats["peak_connections"]` SHALL be at least `2` (one connection per client)
- **THEN** The total connections opened SHALL not exceed `10` (2 clients × 5 max_connections each)
