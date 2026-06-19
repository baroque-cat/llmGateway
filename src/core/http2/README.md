# src/core/http2/ — HTTP/2 Connection Pool Fixes

## Why this exists

Two upstream httpcore bugs cause cascading failures under concurrent load:

- **Bug #1 (Stream Desync, httpcore#1022):** After asyncio task cancellation,
  h2's internal stream state falls out of sync with httpcore's semaphore,
  causing `NoAvailableStreamIDError` → `LocalProtocolError`.
- **Bug #2 (Connection Growth, httpcore#1088):** The connection pool does not
  open new TCP connections when existing HTTP/2 connections reach their
  stream limit because `is_available()` is unaware of H2 stream capacity.

These bugs are fixed upstream in PR #1088 but not yet merged into a
released httpcore version.  This package backports both fixes using
**subclassing** (not monkey-patching).

## What each component does

| File | Class | Responsibility |
|------|-------|---------------|
| `semaphore.py` | `NonBlockingSemaphore(AsyncSemaphore)` | Adds atomic `acquire_nowait()` — non-blocking slot acquisition |
| `h2_connection.py` | `FixedHTTP2Connection(AsyncHTTP2Connection)` | Stream desync fix, non-blocking semaphore, closed-stream tracking, capacity-aware `is_available()`, `max_concurrent_requests()`, `on_capacity_update` callback |
| `connection.py` | `CapacityAwareHTTPConnection(AsyncHTTPConnection)` | Creates `FixedHTTP2Connection` instead of `AsyncHTTP2Connection` when HTTP/2 is negotiated |
| `transport.py` | `CapacityAwareHttp2Transport(AsyncConnectionPool)` | Capacity-aware request routing, per-connection request counting, `on_capacity_update` wiring |

## Integration

The package integrates at a single point — `HttpClientFactory.get_client_for_provider()`:

```python
from src.core.http2 import CapacityAwareHttp2Transport

transport = CapacityAwareHttp2Transport(
    http1=True, http2=True,
    max_connections=..., max_keepalive_connections=..., keepalive_expiry=...,
)
client = httpx.AsyncClient(transport=transport, ...)
```

No global state, no module-level side effects, no monkey-patching.

## When to remove

Delete this entire package when **either**:

1. `encode/httpcore` merges fixes for **both** #1022 and #1088, and
   the project upgrades to that httpcore version.
2. The project migrates away from HTTP/2 (`http2: false` in config)
   for all providers.

The `httpcore==1.0.9` pin in `pyproject.toml` and the CI version check
serve as reminders to re-evaluate after dependency upgrades.

## Architecture constraints

- **Dependency version pinned:** `httpcore==1.0.9` (frozen in `pyproject.toml`,
  `poetry.lock`, `uv.lock`, and CI).
- **No sync transport:** Only async (`AsyncConnectionPool`, `AsyncHTTP2Connection`)
  is overridden.  The project is fully async — sync paths exist only in tests.
- **No proxy support at httpcore level:** The project uses httpx-level proxies
  (`proxy=` parameter), not httpcore-level proxy connections.
- **`handle_async_request` is copied** in both `FixedHTTP2Connection` and
  `CapacityAwareHTTPConnection` because httpcore creates semaphores and
  connections inline inside these methods with no hooks for injection.
  The copies are clearly documented with their origin (httpcore 1.0.9).
