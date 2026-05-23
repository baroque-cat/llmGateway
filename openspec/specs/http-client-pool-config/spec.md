# http-client-pool-config

## Purpose

Provides global HTTP client connection pool configuration (`max_connections`,
`max_keepalive_connections`, `keepalive_expiry`) applicable to both Keeper and
Gateway processes. Enables operators to tune httpx connection pooling for their
deployment, and sets `dedicated_http_client=True` by default for per-provider
connection pool isolation.

## Requirements

### Requirement: Global HTTP client pool configuration
The system SHALL provide a top-level `http_client` configuration section in
`config/providers.yaml` with a nested `pool` subsection controlling httpx
connection pool limits. These settings SHALL be applied by `HttpClientFactory`
to every `httpx.AsyncClient` instance it creates, affecting both the Keeper
and Gateway processes.

#### Scenario: Default pool limits applied
- **WHEN** the YAML config omits the `http_client` section
- **THEN** `HttpClientFactory` SHALL create clients with
  `httpx.Limits(max_connections=100, max_keepalive_connections=20, keepalive_expiry=5.0)`

#### Scenario: Custom pool limits from YAML
- **WHEN** the YAML config contains:
  ```yaml
  http_client:
    pool:
      max_connections: 200
      max_keepalive_connections: 50
      keepalive_expiry: 30.0
  ```
- **THEN** `HttpClientFactory` SHALL create all clients with
  `httpx.Limits(max_connections=200, max_keepalive_connections=50, keepalive_expiry=30.0)`

#### Scenario: Pool limits apply to both Keeper and Gateway
- **WHEN** the Keeper creates an `HttpClientFactory` and the Gateway creates
  an `HttpClientFactory`, both using the same `config/providers.yaml` with
  `http_client.pool.keepalive_expiry: 30.0`
- **THEN** both factories SHALL create clients with `keepalive_expiry=30.0`

### Requirement: HttpClientPoolConfig model
The Pydantic config schema SHALL include an `HttpClientPoolConfig` model with
fields `max_connections: int` (default 100, gt=0),
`max_keepalive_connections: int` (default 20, gt=0), and
`keepalive_expiry: float` (default 5.0, gt=0).

#### Scenario: Pool config validates bounds
- **WHEN** the YAML config contains `max_connections: 0`
- **THEN** Pydantic validation SHALL reject the config with a `ValidationError`

### Requirement: HttpClientConfig model
The Pydantic config schema SHALL include an `HttpClientConfig` model wrapping
`pool: HttpClientPoolConfig` (default factory) and `http2: bool` (default True).
This model SHALL be a field on the root `Config`.

#### Scenario: http2 can be disabled globally
- **WHEN** the YAML config contains `http_client: { http2: false }`
- **THEN** `HttpClientFactory` SHALL create clients without `http2=True`

### Requirement: dedicated_http_client defaults to True
The `ProviderConfig.dedicated_http_client` field SHALL default to `True`,
meaning each provider instance receives its own isolated `httpx.AsyncClient`
unless explicitly overridden.

#### Scenario: New provider gets dedicated client by default
- **WHEN** a provider is defined without a `dedicated_http_client` field
- **THEN** `provider_config.dedicated_http_client` SHALL be `True`
- **AND** `HttpClientFactory` SHALL create a dedicated client for that provider

#### Scenario: Explicit false still works
- **WHEN** a provider is defined with `dedicated_http_client: false`
- **THEN** `provider_config.dedicated_http_client` SHALL be `False`
- **AND** the provider SHALL share a client with other providers using the
  same proxy config
