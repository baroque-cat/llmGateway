## Why

HTTP/2 multiplexing means multiple streams share one TCP connection. The current `httpx.Timeout(read=120)` operates at the socket level — each `socket.receive()` call resets the timer. When other streams on the same connection are active, a starved stream never times out. Production evidence (`docs/CASCADING_FREEZE_EVIDENCE.md`) proves starved streams wait indefinitely until the gateway-level `asyncio.timeout(600)` fires. This change adds a per-stream deadline enforced at the Python event-loop level, making `read` (or a new `stream_read`) actually meaningful for each individual HTTP/2 stream.

## What Changes

- **New config field**: `stream_read: float | None` in `TimeoutConfig` — per-stream deadline for receiving response headers. Default `None` means no per-stream deadline (socket-level `read` timeout remains as backstop). Configurable per-provider (e.g., 300s for DashScope/qwen-home matching their SDK default)
- **Per-stream timeout enforcement**: wrap `_receive_response()` in `FixedHTTP2Connection.handle_async_request` with `asyncio.wait_for(timeout=stream_read or read)`. On timeout: send `RST_STREAM`, release semaphore, propagate error
- **Config injection**: pass `stream_read` through `request.extensions` in `_send_proxy_request`
- **Config audit fixes**: add explicit `timeouts` and `gateway_policy` blocks to `deepseek-main` in `example_full_config.yaml`; add missing `pool_health_log_interval_sec` to `defaults.py`

## Capabilities

### New Capabilities
- `per-stream-response-timeout`: guarantees individual HTTP/2 streams do not wait indefinitely for response headers. Each stream has its own deadline (from `stream_read` or `read` config), enforced via `asyncio.wait_for()` at the event-loop level, immune to socket-level timer reset from other streams' activity

### Modified Capabilities
- `http2-stream-desync-fix`: `FixedHTTP2Connection.handle_async_request` gains per-stream timeout wrapping `_receive_response`
- `http-client-pool-config`: `TimeoutConfig` gains optional `stream_read` field
- `request-lifecycle-timeout`: per-stream timeout documented as primary defense, `total` as backstop

## Impact

- **Affected files**: `schemas.py` (+1 field), `providers/base.py` (+1 line injection), `h2_connection.py` (+15 lines), `defaults.py` (+2 fields), `example_full_config.yaml` (~30 lines config additions), `tests/_canonical.py` (+1 field), test files
- **No breaking API changes**: `stream_read=None` preserves backward compatibility
- **No new dependencies**
