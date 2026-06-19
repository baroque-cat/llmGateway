## Why

Two production HTTP/2 bugs in `httpcore` cause cascading key-burn failures under concurrent load. The current fix is a 357-line monkey-patch (`src/core/httpcore_patch.py`) that replaces methods on foreign classes — an anti-pattern in a codebase built on `I`-prefixed interfaces, polymorphism, and dependency injection. The monkey-patch works (18/18 stress tests pass) but is fragile (Layer 3 copies 100+ lines from httpcore verbatim), unreadable (the change is hidden in a 135-line function), and omits key PR #1088 mechanisms (`on_capacity_update` callback, `acquire_nowait()` atomic acquire). We need to replace the monkey-patch with a subclass-based architecture that matches the project's design philosophy while fully backporting the upstream fix.

## What Changes

- **ADDED** `src/core/http2/` package with subclass-based HTTP/2 fixes (replaces monkey-patch)
- **ADDED** `NonBlockingSemaphore(AsyncSemaphore)` — atomic `acquire_nowait()` method
- **ADDED** `FixedHTTP2Connection(AsyncHTTP2Connection)` — stream desync fix, non-blocking semaphore, closed-stream tracking, capacity-aware `is_available()`
- **ADDED** `CapacityAwareHTTPConnection(AsyncHTTPConnection)` — creates `FixedHTTP2Connection` instead of `AsyncHTTP2Connection`
- **ADDED** `CapacityAwareHttp2Transport(AsyncConnectionPool)` — capacity-aware request routing, `on_capacity_update` callback, `connection_request_count` tracking
- **MODIFIED** `HttpClientFactory.get_client_for_provider()` — creates `CapacityAwareHttp2Transport` and passes it as `transport=` to `httpx.AsyncClient`
- **REMOVED** `src/core/httpcore_patch.py` (357 lines) — obsolete after migration
- **REMOVED** `main.py:23` `apply_patch()` call
- **REMOVED** `tests/stress/conftest.py:19` `apply_patch()` call
- **FROZEN** `httpcore==1.0.9`, `h2>=4.3.0,<5.0` as explicit dependencies in `pyproject.toml`

## Capabilities

### New Capabilities
- `http2-nonblocking-semaphore`: Atomic non-blocking semaphore acquire (`acquire_nowait()`) for httpcore's `AsyncSemaphore`/`Semaphore`
- `http2-stream-desync-fix`: Synchronize h2 stream state with httpcore semaphore after asyncio task cancellation, preventing phantom stream accumulation
- `http2-capacity-aware-pool`: Connection pool that respects H2 stream capacity — opens new TCP connections when existing ones are full, tracks requests-per-connection, fires `on_capacity_update` callback on SETTINGS changes

### Modified Capabilities
<!-- No existing spec-level requirements change. This is a pure implementation replacement — behavior is preserved, only architecture changes. -->

## Impact

- **Affected code**: `src/core/http2/` (new, ~400 lines), `src/core/http_client_factory.py` (+10 lines), `main.py` (-1 line), `tests/stress/conftest.py` (-1 line)
- **Removed code**: `src/core/httpcore_patch.py` (-357 lines), `tests/stress/test_stream_desync_patch.py` (-146 lines)
- **Dependencies**: `httpcore==1.0.9`, `h2>=4.3.0,<5.0` frozen explicitly in `pyproject.toml`
- **Backward compatibility**: Full — same behavior, different architecture. All 18 stress tests must pass unchanged (except the desync patch test which becomes a unit test for `FixedHTTP2Connection`)
