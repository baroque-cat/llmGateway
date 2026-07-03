## ADDED Requirements

### Requirement: Per-provider max_concurrent_streams cap

`ProviderConfig` SHALL include a `max_concurrent_streams_per_connection: int` field
(default=5, ge=1, le=1000) that caps the effective `MAX_CONCURRENT_STREAMS` per H2
TCP connection for that provider. The actual effective cap SHALL be
`min(config_value, server_advertised_MAX_CONCURRENT_STREAMS, local_settings=100)`.

#### Scenario: Default cap of 5 applied

- **WHEN** a provider is defined without `max_concurrent_streams_per_connection` in YAML
- **THEN** `provider_config.max_concurrent_streams_per_connection` SHALL be `5`
- **AND** `FixedHTTP2Connection._max_streams` SHALL be `min(server_advertised, 100, 5)`

#### Scenario: Custom cap from YAML

- **WHEN** a provider is defined with `max_concurrent_streams_per_connection: 100`
- **THEN** `FixedHTTP2Connection._max_streams` SHALL be `min(server_advertised, 100, 100)`
- **AND** if the server advertises 100, the effective cap SHALL be 100

#### Scenario: Cap lower than server-advertised value

- **WHEN** `max_concurrent_streams_per_connection=5` and the server advertises `MAX_CONCURRENT_STREAMS=100`
- **THEN** `FixedHTTP2Connection._max_streams` SHALL be `5`
- **AND** the pool SHALL open a new TCP connection after 5 concurrent streams on one connection

#### Scenario: Cap higher than server-advertised value

- **WHEN** `max_concurrent_streams_per_connection=100` and the server advertises `MAX_CONCURRENT_STREAMS=3`
- **THEN** `FixedHTTP2Connection._max_streams` SHALL be `3`
- **AND** the cap SHALL NOT raise the effective limit above what the server advertises

#### Scenario: H1 providers unaffected

- **WHEN** `max_concurrent_streams_per_connection=5` and the connection negotiates HTTP/1.1 (no H2)
- **THEN** `FixedHTTP2Connection` SHALL NOT be created
- **AND** the cap SHALL NOT apply (HTTP/1.1 has no stream multiplexing)

#### Scenario: Cap validates bounds

- **WHEN** the YAML config contains `max_concurrent_streams_per_connection: 0`
- **THEN** Pydantic validation SHALL reject the config with a `ValidationError`

#### Scenario: Cap passed through the transport chain

- **WHEN** `HttpClientFactory.get_client_for_provider(name)` creates a transport
- **THEN** the `max_concurrent_streams_per_connection` value from `ProviderConfig` SHALL be passed to `CapacityAwareHttp2Transport`
- **AND** through to `CapacityAwareHttp2Pool`
- **AND** through to `CapacityAwareHTTPConnection`
- **AND** through to `FixedHTTP2Connection.__init__`

### Requirement: Connection labels

`CapacityAwareHttp2Pool` SHALL assign a human-readable label to each connection it
creates. The label format SHALL be `{provider_name}-conn-{ordinal}` where ordinal
is a per-pool monotonic counter starting at 0.

#### Scenario: Connection label assigned on creation

- **WHEN** `CapacityAwareHttp2Pool.create_connection(origin)` creates a new `CapacityAwareHTTPConnection`
- **THEN** the connection SHALL receive a label `"{provider_name}-conn-{N}"` where N is the next ordinal
- **AND** the ordinal counter SHALL increment

#### Scenario: Multiple connections get sequential labels

- **WHEN** the pool creates 3 connections for provider `qwen-home`
- **THEN** the labels SHALL be `qwen-home-conn-0`, `qwen-home-conn-1`, `qwen-home-conn-2`

#### Scenario: Label stored on connection

- **WHEN** a `CapacityAwareHTTPConnection` is created with a label
- **THEN** the label SHALL be accessible as `connection._connection_label`
- **AND** the label SHALL be included in the connection's `__repr__` if overridden

### Requirement: Pool opens new connection when cap reached

`CapacityAwareHttp2Pool._assign_requests_to_connections()` SHALL respect the capped
`max_concurrent_requests()` value. When all existing connections are at their capped
capacity, the pool SHALL open a new TCP connection (up to `max_connections`).

#### Scenario: Cap forces second connection

- **WHEN** `max_concurrent_streams_per_connection=5` and 6 concurrent requests are sent through one pool
- **THEN** the first connection SHALL receive 5 streams
- **AND** the pool SHALL open a second connection for the 6th stream
- **AND** `peak_connections` SHALL be `2`

#### Scenario: All requests complete with cap

- **WHEN** `max_concurrent_streams_per_connection=5` and 10 concurrent requests are sent against a server with `internal_concurrency=8`
- **THEN** all 10 requests SHALL complete successfully
- **AND** no request SHALL experience a cascading freeze
