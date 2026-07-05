## MODIFIED Requirements

### Requirement: Gateway logs pool health periodically at INFO level

The gateway SHALL run a background task that logs pool health summaries at a configurable interval when the gateway is active.

#### Scenario: Health log line format

- **WHEN** the health logging task executes
- **THEN** one INFO-level log line is emitted per cached client with format: `HTTP_POOL_HEALTH | <cache_key> | conns: <total> total (<active> active, <idle> idle) | proto: <h2> H2 / <h1> H1 | streams: <active> active / <max> max_capacity | queued: <queued>`
- **AND** when per-connection details are available, an additional line per connection is emitted with format: `HTTP_POOL_CONN | <cache_key> | <label> | <state> | <protocol> | streams: <active>/<max>`

#### Scenario: Health logging respects configured interval

- **WHEN** `pool_health_log_interval_sec` is set to `N` seconds (N > 0)
- **THEN** the background task executes approximately every `N` seconds

#### Scenario: Health logging disabled when interval is zero

- **WHEN** `pool_health_log_interval_sec` is set to `0`
- **THEN** the background task is not started, and no health log lines are emitted

#### Scenario: Health logging disabled when interval attribute is inaccessible

- **WHEN** the gateway lifespan accesses `factory._pool_health_log_interval_sec` and the attribute does not resolve to an integer (e.g., during testing where `HttpClientFactory` is replaced with a `MagicMock`)
- **THEN** the health logging background task is NOT started
- **AND** no `TypeError` is raised
- **AND** the gateway startup continues normally

#### Scenario: Health logging interval configurable

- **WHEN** `pool_health_log_interval_sec` is not specified in config
- **THEN** the default value `60` (seconds) is used

## ADDED Requirements

### Requirement: Gateway lifespan startup is resilient to HttpClientFactory substitution

The gateway lifespan startup SHALL use `getattr(factory, "_pool_health_log_interval_sec", 0)` to access the pool health log interval, rather than direct attribute access. This ensures that when `HttpClientFactory` is substituted (e.g., by a test mock), the lifespan gracefully degrades by disabling the health log loop rather than raising a `TypeError`.

#### Scenario: Real HttpClientFactory starts health loop normally

- **WHEN** `HttpClientFactory` is a real instance with `_pool_health_log_interval_sec = 60`
- **THEN** `getattr(factory, "_pool_health_log_interval_sec", 0)` returns `60`
- **AND** `60 > 0` evaluates to `True`
- **AND** the health logging background task is started

#### Scenario: Mocked HttpClientFactory falls back gracefully

- **WHEN** `HttpClientFactory` is a `MagicMock` instance (returned by `patch("...HttpClientFactory")` as `MockHttpClientFactory.return_value`)
- **AND** no explicit `_pool_health_log_interval_sec` attribute is set on the mock
- **THEN** `getattr(factory, "_pool_health_log_interval_sec", 0)` returns `0`
- **AND** `0 > 0` evaluates to `False`
- **AND** the health logging background task is NOT started
- **AND** no exception is raised
