## MODIFIED Requirements

### Requirement: Pool exposes health summary method

`CapacityAwareHttp2Pool` SHALL provide a `get_health_summary()` method returning a
dictionary with current pool-level statistics, including both aggregate counts and
a per-connection breakdown list.

#### Scenario: Health summary returns connection counts

- **WHEN** `get_health_summary()` is called on an active pool
- **THEN** the returned dict contains keys `total_connections`, `active_connections`, `idle_connections` with non-negative integer values, and `total == active + idle`

#### Scenario: Health summary returns protocol split

- **WHEN** `get_health_summary()` is called
- **THEN** the returned dict contains keys `h2_connections` and `h1_connections` counting connections by protocol type

#### Scenario: Health summary returns stream metrics

- **WHEN** `get_health_summary()` is called and at least one H2 connection exists
- **THEN** the returned dict contains keys `active_h2_streams` and `max_h2_stream_capacity` reflecting the sum across all H2 connections

#### Scenario: Health summary returns queue depth

- **WHEN** `get_health_summary()` is called
- **THEN** the returned dict contains key `queued_requests` with the count of requests awaiting connection assignment

#### Scenario: Health summary returns per-connection breakdown

- **WHEN** `get_health_summary()` is called on a pool with connections
- **THEN** the returned dict contains key `connections` with a list of per-connection dicts
- **AND** each dict contains `label` (str), `state` (str), `protocol` (str), `active_streams` (int), `max_streams` (int)

### Requirement: Gateway logs pool health periodically at INFO level

The gateway SHALL run a background task that logs pool health summaries at a
configurable interval when the gateway is active. The log line SHALL include
per-connection details when connections exist.

#### Scenario: Health log line format

- **WHEN** the health logging task executes
- **THEN** one INFO-level log line is emitted per cached client with format: `HTTP_POOL_HEALTH | <cache_key> | conns: <total> total (<active> active, <idle> idle) | proto: <h2> H2 / <h1> H1 | streams: <active> active / <max> max_capacity | queued: <queued>`
- **AND** when per-connection details are available, an additional line per connection is emitted with format: `HTTP_POOL_CONN | <cache_key> | <label> | <state> | <protocol> | streams: <active>/<max>`

#### Scenario: Health logging respects configured interval

- **WHEN** `pool_health_log_interval_sec` is set to `N` seconds (N > 0)
- **THEN** the background task executes approximately every `N` seconds

#### Scenario: Health logging disabled when interval is zero

- **WHEN** `pool_health_log_interval_sec` is set to `0`
- **THEN** the background task SHALL NOT execute
