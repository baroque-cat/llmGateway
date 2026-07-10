## Why

Under upstream degradation (DashScope queue saturation), HTTP/2 stream semaphore slots leak permanently — connections accumulate to 5/5 streams and never recover until gateway restart. The root cause is two code defects in `StreamMonitor.__anext__` and `_handle_buffered_retryable_request` timeout handling where `upstream_response.aclose()` is never called, causing `NonBlockingSemaphore` slots to leak forever. Production logs show connections stuck at 5/5 for 29+ minutes with cascading 600s timeouts.

## What Changes

- **StreamMonitor**: add `finally` block in `__anext__` so `_finalize_logging()` + `aclose()` executes on ALL exit paths including `CancelledError` and `GeneratorExit` (both `BaseException` subclasses that bypass the current `except Exception`)
- **StreamMonitor**: add `_finalized` guard flag to prevent double-invocation of `_finalize_logging()` when `StopAsyncIteration` triggers both the `except` re-raise and the new `finally`
- **StreamMonitor**: wrap `aclose()` call in `try/except` to prevent exceptions from masking original errors during `finally` cleanup
- **Timeout handler**: hoist `upstream_response` and `body_bytes` variables outside the while-loop, add `finally` block that calls `discard_response()` to guarantee upstream stream closure when `asyncio.timeout(600s)` fires

## Capabilities

### New Capabilities
- `stream-monitor-graceful-shutdown`: guarantees `upstream_response.aclose()` is called on ALL exit paths from `StreamMonitor.__anext__` — including `CancelledError` (client disconnect), `GeneratorExit` (async generator cleanup), `StopAsyncIteration` (normal completion), `httpx.ReadError` (upstream disconnect), and unexpected exceptions

### Modified Capabilities
- `request-lifecycle-timeout`: the `except TimeoutError` handler in `_handle_buffered_retryable_request` must guarantee upstream response stream closure via `discard_response()` in a `finally` block, rather than leaving the stream dangling

## Impact

- **Affected code**: `src/services/gateway/gateway_service.py` (StreamMonitor class + `_handle_buffered_retryable_request` function, ~40 lines changed)
- **Affected tests**: `tests/unit/services/test_gateway_service_stream_monitor.py` (3 new tests), `tests/unit/services/test_gateway_timeout.py` (1 new test)
- **No API changes, no config changes, no new dependencies**
- **No breaking changes** to any public interface
