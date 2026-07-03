## MODIFIED Requirements

### Requirement: dedicated_http_client defaults to True

**REMOVED** — The `dedicated_http_client` field is removed from `ProviderConfig`.
All providers now always receive a dedicated `httpx.AsyncClient` with an isolated
connection pool. The shared-client code path (`_get_cache_key_for_proxy`,
`"__none__"` cache key) is deleted.

**Reason**: The field was always `True` in all example configs and defaults. The
`False` path added complexity (21 lines of dead code, ~12 tests, known collision
vulnerability) without value. Removing it simplifies the factory and eliminates
the `__none__` collision.

**Migration**: Remove `dedicated_http_client: true` lines from YAML configs. The
field is no longer accepted (`extra="forbid"` on `ProviderConfig`).

#### Scenario: Provider always gets dedicated client

- **WHEN** a provider is defined in YAML (with or without any http client fields)
- **THEN** `HttpClientFactory._get_cache_key_for_provider(name)` SHALL return `name`
- **AND** the provider SHALL receive its own isolated `httpx.AsyncClient`

#### Scenario: No shared client path

- **WHEN** two providers use the same proxy URL
- **THEN** each provider SHALL still receive its own `httpx.AsyncClient`
- **AND** the clients SHALL NOT share a connection pool

## ADDED Requirements

### Requirement: Per-provider max_concurrent_streams_per_connection field

`ProviderConfig` SHALL include a `max_concurrent_streams_per_connection: int` field
with `default=5`, `ge=1`, `le=1000`. This field is per-provider, not global.

#### Scenario: Field defaults to 5

- **WHEN** a provider is defined without `max_concurrent_streams_per_connection` in YAML
- **THEN** `provider_config.max_concurrent_streams_per_connection` SHALL be `5`

#### Scenario: Field set in YAML

- **WHEN** a provider is defined with `max_concurrent_streams_per_connection: 100`
- **THEN** `provider_config.max_concurrent_streams_per_connection` SHALL be `100`

#### Scenario: Field validates bounds

- **WHEN** the YAML config contains `max_concurrent_streams_per_connection: 0`
- **THEN** Pydantic validation SHALL reject the config with a `ValidationError`

#### Scenario: Field rejects values above 1000

- **WHEN** the YAML config contains `max_concurrent_streams_per_connection: 1001`
- **THEN** Pydantic validation SHALL reject the config with a `ValidationError`
