## MODIFIED Requirements

### Requirement: Transport opens new TCP connections when H2 streams are full

`CapacityAwareHttp2Pool(AsyncConnectionPool)` SHALL route requests to connections
with available H2 stream capacity, and open new TCP connections when existing
connections are full. The capacity check SHALL respect the per-connection
`max_concurrent_requests()` value, which is capped by
`max_concurrent_streams_per_connection` when set.

#### Scenario: Existing connection has available streams

- **WHEN** `_assign_requests_to_connections()` evaluates a connection with `connection_request_count[conn] < _max_concurrent_requests(conn)` and `is_available()` returns `True`
- **THEN** the request is assigned to that connection and `connection_request_count` is incremented

#### Scenario: All connections are full, pool has room

- **WHEN** all existing connections have `connection_request_count[conn] >= _max_concurrent_requests(conn)` and `len(self._connections) < self._max_connections`
- **THEN** a new connection is created via `create_connection()`, added to the pool, and the request is assigned to it

#### Scenario: Pool is also full

- **WHEN** all connections are full and `len(self._connections) >= self._max_connections`
- **THEN** the pool attempts to close an idle connection and create a new one; if no idle connection exists, the request remains queued

#### Scenario: Cap forces new connection before server-advertised limit

- **WHEN** `max_concurrent_streams_per_connection=5` and a connection's `max_concurrent_requests()` returns 5 (capped from server's 100)
- **AND** 5 requests are already assigned to that connection
- **THEN** the pool SHALL NOT assign a 6th request to that connection
- **AND** the pool SHALL open a new connection (if under `max_connections`)

## ADDED Requirements

### Requirement: Connection labels in pool

`CapacityAwareHttp2Pool` SHALL assign a human-readable label to each connection
created via `create_connection()`. The label format SHALL be
`{provider_name}-conn-{ordinal}` where ordinal is a per-pool monotonic counter
starting at 0.

#### Scenario: Label assigned on creation

- **WHEN** `create_connection(origin)` creates a new `CapacityAwareHTTPConnection`
- **THEN** the connection SHALL receive `connection_label="{provider_name}-conn-{N}"`
- **AND** the pool's internal ordinal counter SHALL increment

#### Scenario: Multiple connections sequential labels

- **WHEN** the pool creates 3 connections for provider `qwen-home`
- **THEN** labels SHALL be `qwen-home-conn-0`, `qwen-home-conn-1`, `qwen-home-conn-2`

### Requirement: Per-connection health breakdown

`CapacityAwareHttp2Pool.get_health_summary()` SHALL include a `connections` key
containing a list of per-connection detail dicts, in addition to the existing
aggregate keys.

#### Scenario: Per-connection details in health summary

- **WHEN** `get_health_summary()` is called on a pool with 2 H2 connections
- **THEN** the returned dict SHALL contain key `connections` with a list of 2 dicts
- **AND** each dict SHALL contain keys `label` (str), `state` (str), `protocol` (str), `active_streams` (int), `max_streams` (int)

#### Scenario: Empty pool returns empty connections list

- **WHEN** `get_health_summary()` is called on a pool with no connections
- **THEN** the `connections` list SHALL be empty

### Requirement: Connection creation and closure logging

`CapacityAwareHttp2Pool` SHALL log connection creation and closure events at INFO
level with the connection label.

#### Scenario: Connection creation logged

- **WHEN** `create_connection(origin)` creates a new connection with label `qwen-home-conn-0`
- **THEN** an INFO log line SHALL be emitted containing the label and origin

#### Scenario: Connection closure logged

- **WHEN** a connection with label `qwen-home-conn-0` is closed (via `aclose()` or eviction)
- **THEN** an INFO log line SHALL be emitted containing the label and closure reason
