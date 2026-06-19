## ADDED Requirements

### Requirement: Pool exposes health summary method

`CapacityAwareHttp2Pool` SHALL provide a `get_health_summary()` method returning a dictionary with current pool-level statistics.

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

### Requirement: Factory aggregates health summaries across all clients

`HttpClientFactory` SHALL provide a `get_pool_health_summary()` method returning a mapping from cache key to pool health summary for all currently cached HTTP clients.

#### Scenario: Health summaries for all cached clients

- **WHEN** `get_pool_health_summary()` is called
- **THEN** the returned `dict[str, dict]` contains one entry per key in `_clients`, each value being the result of `CapacityAwareHttp2Pool.get_health_summary()` for that client's pool

#### Scenario: Empty cache returns empty dict

- **WHEN** `get_pool_health_summary()` is called and no clients are cached
- **THEN** an empty dict is returned

### Requirement: Gateway logs pool health periodically at INFO level

The gateway SHALL run a background task that logs pool health summaries at a configurable interval when the gateway is active.

#### Scenario: Health log line format

- **WHEN** the health logging task executes
- **THEN** one INFO-level log line is emitted per cached client with format: `HTTP_POOL_HEALTH | <cache_key> | conns: <total> total (<active> active, <idle> idle) | proto: <h2> H2 / <h1> H1 | streams: <active> active / <max> max_capacity | queued: <queued>`

#### Scenario: Health logging respects configured interval

- **WHEN** `pool_health_log_interval_sec` is set to `N` seconds (N > 0)
- **THEN** the background task executes approximately every `N` seconds

#### Scenario: Health logging disabled when interval is zero

- **WHEN** `pool_health_log_interval_sec` is set to `0`
- **THEN** the background task is not started, and no health log lines are emitted

#### Scenario: Health logging interval configurable

- **WHEN** `pool_health_log_interval_sec` is not specified in config
- **THEN** the default value `60` (seconds) is used
