# http2-capacity-aware-pool

Capacity-aware HTTP/2 connection pool that respects per-connection stream limits, tracks per-connection request counts, fires `on_capacity_update` callbacks, and opens new TCP connections when existing H2 connections reach their stream capacity.

## Requirements

### Requirement: Transport opens new TCP connections when H2 streams are full

`CapacityAwareHttp2Pool(AsyncConnectionPool)` SHALL route requests to connections with available H2 stream capacity, and open new TCP connections when existing connections are full.

#### Scenario: Existing connection has available streams

- **WHEN** `_assign_requests_to_connections()` evaluates a connection with `connection_request_count[conn] < _max_concurrent_requests(conn)` and `is_available()` returns `True`
- **THEN** the request is assigned to that connection and `connection_request_count` is incremented

#### Scenario: All connections are full, pool has room

- **WHEN** all existing connections have `connection_request_count[conn] >= _max_concurrent_requests(conn)` and `len(self._connections) < self._max_connections`
- **THEN** a new connection is created via `create_connection()`, added to the pool, and the request is assigned to it

#### Scenario: Pool is also full

- **WHEN** all connections are full and `len(self._connections) >= self._max_connections`
- **THEN** the pool attempts to close an idle connection and create a new one; if no idle connection exists, the request remains queued

### Requirement: Transport tracks requests assigned to each connection

`CapacityAwareHttp2Pool._assign_requests_to_connections()` SHALL maintain a `connection_request_count` dictionary that counts how many requests are currently assigned to each connection.

#### Scenario: Request assigned to connection

- **WHEN** `pool_request.assign_to_connection(connection)` is called
- **THEN** `connection_request_count[connection]` is incremented by 1

#### Scenario: Initial count

- **WHEN** `_assign_requests_to_connections()` begins
- **THEN** `connection_request_count` is initialized from `self._requests` — counting requests already assigned to each connection

### Requirement: Transport queries connection capacity

`CapacityAwareHttp2Pool._max_concurrent_requests(connection)` SHALL return the maximum number of concurrent requests the connection supports.

#### Scenario: Connection supports max_concurrent_requests()

- **WHEN** `_max_concurrent_requests(connection)` is called on a connection with the method
- **THEN** returns the result of `connection.max_concurrent_requests()`

#### Scenario: Connection does not support max_concurrent_requests()

- **WHEN** `_max_concurrent_requests(connection)` is called on a connection without the method (AttributeError)
- **THEN** returns `1` (fallback for HTTP/1.1 and unpatched connections)

### Requirement: Transport wires on_capacity_update callback

`CapacityAwareHttp2Pool.create_connection()` SHALL pass `on_capacity_update=self._connection_capacity_updated` to all created connections.

#### Scenario: Connection created

- **WHEN** `create_connection(origin)` creates a new `CapacityAwareHTTPConnection`
- **THEN** the connection receives `on_capacity_update=self._connection_capacity_updated`

### Requirement: Capacity callback triggers request reassignment

`CapacityAwareHttp2Pool._connection_capacity_updated()` SHALL re-run `_assign_requests_to_connections()` and close any removed connections.

#### Scenario: Connection signals capacity change

- **WHEN** `_connection_capacity_updated()` is called
- **THEN** `_assign_requests_to_connections()` is executed under `_optional_thread_lock`, and returned closing connections are passed to `_close_connections()`

### Requirement: Transport is a pluggable httpx transport

`CapacityAwareHttp2Transport` SHALL be usable as the `transport=` argument to `httpx.AsyncClient`.

#### Scenario: httpx uses custom transport

- **WHEN** `httpx.AsyncClient(transport=CapacityAwareHttp2Transport(...))` is created
- **THEN** all HTTP requests through that client use the capacity-aware pool for connection management

### Requirement: CapacityAwareHTTPConnection creates FixedHTTP2Connection

`CapacityAwareHTTPConnection(AsyncHTTPConnection)` SHALL create `FixedHTTP2Connection` instead of `AsyncHTTP2Connection` when HTTP/2 is negotiated.

#### Scenario: HTTP/2 negotiated

- **WHEN** `handle_async_request()` negotiates HTTP/2 (ALPN or `self._http2 and not self._http1`)
- **THEN** the internal connection is `FixedHTTP2Connection(..., on_capacity_update=self._on_capacity_update)`

#### Scenario: HTTP/1.1 negotiated

- **WHEN** `handle_async_request()` negotiates HTTP/1.1
- **THEN** the internal connection is `AsyncHTTP11Connection(...)` (unchanged from httpcore)
