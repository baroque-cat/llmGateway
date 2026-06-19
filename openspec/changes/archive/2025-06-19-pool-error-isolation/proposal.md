## Why

When the HTTP/2 connection pool saturates (all streams on all connections are busy), `httpx.LocalProtocolError` propagates into `_send_proxy_request` and is misclassified as `ErrorReason.NETWORK_ERROR` — a retryable server error. The gateway then retries with the same key, and after exhaustion penalizes the key, initiating a cascade that burns through the entire key pool. The failure is a purely local pool-saturation problem — nothing to do with the API key. Separately, operators have no visibility into pool/stream health at runtime (how many connections, streams, queued requests exist per provider), making it impossible to detect saturation proactively.

## What Changes

- **MODIFIED** `AIBaseProvider._send_proxy_request()` — adds detection of `httpx.LocalProtocolError`, mapping it to `ErrorReason.BAD_REQUEST` (a client-side error that bypasses retry and key penalization). All other `httpx.RequestError` subclasses continue mapping to `ErrorReason.NETWORK_ERROR`.
- **ADDED** `CapacityAwareHttp2Pool.get_health_summary()` — returns a dict with current pool statistics: total/active/idle connections, H2 vs H1 split, active H2 streams, max stream capacity, queued requests.
- **ADDED** `HttpClientFactory.get_pool_health_summary()` — iterates over all cached clients and collects their pool health summaries.
- **ADDED** `_pool_health_log_loop()` background task in gateway lifespan — logs pool health at configurable interval (default 60 s) at INFO level.
- **ADDED** `pool_health_log_interval_sec` field to `HttpClientConfig` — 0 disables the loop.

## Capabilities

### New Capabilities
- `pool-error-isolation`: Distinguish pool-level `LocalProtocolError` from upstream network errors in the request pipeline, preventing false key penalization.
- `pool-health-logging`: Periodic INFO-level logging of HTTP connection pool state per provider (connections, streams, queue depth).

### Modified Capabilities
<!-- No existing spec-level requirement changes. -->

## Impact

- **Affected code**: `src/providers/base.py` (+10 lines), `src/core/http2/pool.py` (+25 lines), `src/core/http_client_factory.py` (+15 lines), `src/services/gateway/gateway_service.py` (+30 lines), `src/config/schemas.py` (+5 lines)
- **New tests**: `tests/unit/providers/test_base.py` (1 test for `LocalProtocolError` → `BAD_REQUEST`), `tests/unit/core/http2/test_transport.py` (1 test for `get_health_summary`), `tests/unit/core/test_http_client_factory.py` (1 test for `get_pool_health_summary`)
- **Configuration**: New optional field `pool_health_log_interval_sec` in `http_client` config block (default 60, 0 = disabled)
- **Backward compatibility**: Full — existing error classification unchanged except `LocalProtocolError` (previously `NETWORK_ERROR`, now `BAD_REQUEST`). All other error mappings preserved.
