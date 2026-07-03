## Why

Production anomaly: 10 agents hitting a single provider (qwen-home) cause all
requests to freeze beyond ~8 concurrent H2 streams on one TCP connection. The
pool trusts the server-advertised `MAX_CONCURRENT_STREAMS=100` and never opens
a second connection, while the server internally queues beyond 8. The
socket-level read timeout (120 s) does not fire for starved streams because
data for active streams keeps the socket busy. Only the 600 s wall-clock
timeout kills them — minutes of total freeze. Restart temporarily fixes it.

## What Changes

- **BREAKING**: Remove `dedicated_http_client` field from `ProviderConfig`.
  All providers now always get a dedicated `httpx.AsyncClient` (the previous
  default was already `True`; the `False` shared-client path is removed
  entirely, along with `_get_cache_key_for_proxy`).
- Add `max_concurrent_streams_per_connection: int` field to `ProviderConfig`
  (default=5, ge=1, le=1000). This caps the effective H2 streams per TCP
  connection for that provider. The actual cap is
  `min(config_value, server_advertised, local_settings=100)`.
- Pass the cap through the chain: `HttpClientFactory` →
  `CapacityAwareHttp2Transport` → `CapacityAwareHttp2Pool` →
  `CapacityAwareHTTPConnection` → `FixedHTTP2Connection`.
- Apply the cap in `FixedHTTP2Connection._receive_remote_settings_change`
  (the `min()` call) and `handle_async_request` (semaphore initialization).
- Add connection labels: each `CapacityAwareHTTPConnection` created by the
  pool receives a `{provider_name}-conn-{ordinal}` label. The ordinal is a
  per-pool monotonic counter.
- Extend `get_health_summary()` to include a `connections` list with
  per-connection details (label, state, protocol, active_streams,
  max_streams).
- Log connection creation and closure at INFO level with the connection label.
- Update `defaults.py`, `example_full_config.yaml`, and existing tests to
  reflect the removed field and new field.

## Capabilities

### New Capabilities

- `h2-stream-cap`: Per-provider configuration capping the effective
  `MAX_CONCURRENT_STREAMS` per H2 connection, forcing the pool to open
  additional TCP connections when the cap is reached. Includes connection
  labeling and per-connection health reporting.

### Modified Capabilities

- `http-client-pool-config`: Remove the `dedicated_http_client` field and
  its shared-client cache-key logic. Add
  `max_concurrent_streams_per_connection` to `ProviderConfig` (per-provider,
  not global).
- `http2-capacity-aware-pool`: Apply the per-connection stream cap in
  `FixedHTTP2Connection`. Add connection labels and per-connection breakdown
  in `get_health_summary()`.
- `pool-health-logging`: Log per-connection details (label, state, streams)
  alongside the existing aggregate summary. Log connection creation/closure
  events with labels.

## Impact

- **Config schema** (`src/config/schemas.py`): `ProviderConfig` loses
  `dedicated_http_client`, gains `max_concurrent_streams_per_connection`.
  `HttpClientPoolConfig` and `HttpClientConfig` are unchanged.
- **Config defaults** (`src/config/defaults.py`): Remove
  `dedicated_http_client` from the provider template. The new field's
  Pydantic default (5) applies automatically.
- **Example config** (`config/example_full_config.yaml`): Remove
  `dedicated_http_client` lines from all 4 providers. Add
  `max_concurrent_streams_per_connection` with per-provider values.
- **HttpClientFactory** (`src/core/http_client_factory.py`): Simplify
  `_get_cache_key_for_provider` to always return `provider_name`. Delete
  `_get_cache_key_for_proxy`. Read `max_concurrent_streams_per_connection`
  from `ProviderConfig` in `get_client_for_provider` and pass to transport.
- **HTTP/2 transport** (`src/core/http2/transport.py`): Accept
  `max_concurrent_streams_cap` and `provider_name` parameters, pass to pool.
- **HTTP/2 pool** (`src/core/http2/pool.py`): Accept
  `max_concurrent_streams_cap` and `provider_name`. Assign connection labels
  in `create_connection`. Extend `get_health_summary()` with per-connection
  list.
- **HTTP/2 connection** (`src/core/http2/connection.py`): Accept and store
  `connection_label` and `max_concurrent_streams_cap`. Pass cap to
  `FixedHTTP2Connection`.
- **H2 connection** (`src/core/http2/h2_connection.py`): Accept
  `max_concurrent_streams_cap`. Apply in `_receive_remote_settings_change`
  and `handle_async_request`.
- **Tests**: ~12 tests for `dedicated_http_client=False` behavior must be
  rewritten. New unit tests for cap logic, connection labels, and
  per-connection health. New stress test proving the cap prevents the
  cascading freeze.
- **No database schema changes.**
- **No new dependencies.**
- **Runtime mode**: Both Keeper and Gateway affected (both use
  `HttpClientFactory`).
- **Breaking config change**: YAML configs containing
  `dedicated_http_client: false` will be rejected (`extra="forbid"` on
  `ProviderConfig`). All existing example configs use `true` (the default),
  so the field can simply be removed from YAML files.
