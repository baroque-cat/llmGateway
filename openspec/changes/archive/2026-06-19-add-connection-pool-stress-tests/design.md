## Context

In production under multi-agent load (10+ concurrent opencode agents hitting deepseek via the Conductor), httpx's HTTP/2 connection pool hits its per-connection stream limit (128), producing `LocalProtocolError`. The retry logic in `_handle_buffered_retryable_request` reclassifies this as `NETWORK_ERROR` (a retryable server error), triggering cascading key penalization. Each retry attempt creates additional load on the already-saturated pool, burning through keys until the system is restarted.

The existing unit tests for `HttpClientFactory` (`tests/unit/core/test_http_client_factory.py`) verify logical correctness (cache key derivation, client isolation, pool limit values) but mock `httpx.AsyncClient` entirely — no real TCP connections or H2 frames are ever exchanged. This class of pool-level defect is invisible to CI.

We need a test harness that exercises the real `httpx.AsyncClient` against a controlled HTTP/2 server, with configurable stream limits and measurable connection metrics, to determine whether the problem originates in httpx's pool management under our `Limits` configuration.

## Goals / Non-Goals

**Goals:**
- Build an ephemeral HTTP/2 server (`EphemeralHttp2Server`) that can be configured with `SETTINGS_MAX_CONCURRENT_STREAMS`, response delay, and per-connection metrics
- Build a `MetricsCollector` that aggregates connection/stream metrics from the server, httpx trace events, and (optionally) OS-level TCP socket inspection
- Write 6 stress tests that exercise real `httpx.AsyncClient` instances under controlled concurrency, latency, and connection limits
- Prove or disprove that httpx correctly opens new connections when H2 streams are exhausted
- Reproduce the `LocalProtocolError` in a controlled environment
- All tests SHALL run without a database, without Docker, and without API keys

**Non-Goals:**
- Fixing the root cause (pool configuration, error classification, retry logic) — this change only ADDS the test infrastructure
- Testing the full Gateway stack (FastAPI, GatewayCache, DatabaseManager) — these are isolated httpx-level tests
- Testing with real upstream providers (deepseek, anthropic, etc.)
- Performance benchmarking — these are correctness/reproducibility tests

## Decisions

### Decision 1: Raw asyncio + h2 server, NOT hypercorn or aiohttp

**Alternatives considered:**
- **hypercorn**: Supports HTTP/2, but `h2_max_concurrent_streams` control is limited to server-level config, not per-connection. Cannot programmatically change limits mid-test. Adds a dependency.
- **aiohttp**: HTTP/1.1 only. Cannot test H2 stream multiplexing.
- **Raw asyncio + h2**: Full control over `SETTINGS_MAX_CONCURRENT_STREAMS`, per-connection counters, response delay injection. h2 is already installed as a transitive dependency of `httpx[http2]`. ~300 lines of straightforward protocol code.

**Rationale:** The h2 library provides the exact control we need without new dependencies. The protocol handling is well-documented and limited to a single-request-per-stream model (no server push, no trailers, no priority frames).

### Decision 2: Metrics from 3 sources, not a single aggregated view

**Sources:**
1. **Server counters** (`EphemeralHttp2Server.stats`): active_connections, active_streams, total_requests, peak_concurrent_streams — the server's perspective
2. **httpx trace events**: `connection_created`, `connection_closed`, `request_start`, `response_end` — the client's perspective on connection lifecycle
3. **OS TCP inspection** (optional, via `/proc/net/tcp` or `ss`): ESTABLISHED sockets — ground truth, but platform-dependent

**Rationale:** Each source answers a different question. Server counters tell us "did requests arrive?" httpx trace tells us "did httpx think it opened enough connections?" OS inspection tells us "how many TCP sockets actually exist?" Cross-referencing these sources is what proves or disproves the bug.

### Decision 3: Session-scoped server fixture with factory pattern

```python
@pytest_asyncio.fixture(scope="session")
async def http2_server_factory():
    servers = []
    async def _create(**kwargs):
        s = EphemeralHttp2Server(**kwargs)
        await s.start()
        servers.append(s)
        return s
    yield _create
    for s in servers:
        await s.stop()
```

**Rationale:** A session-scoped factory lets each test function create its own server with specific parameters (stream limit, delay) while reusing the same event loop. Cleanup is guaranteed. This avoids the complexity of per-function server lifecycle. `@pytest_asyncio.fixture` is used instead of `@pytest.fixture` because pytest 9 + pytest-asyncio strict mode requires it for async session-scoped fixtures.

### Decision 4: No Gateway or HttpClientFactory involvement in tests 1-4 and 6

Tests 1-4 and 6 directly create `httpx.AsyncClient` instances with explicit `Limits`. This isolates the test to the httpx layer. Only Test 5 (multi-worker) would involve the Gateway, and even that can be simplified to multi-process client creation.

**Rationale:** If we can prove the bug exists at the httpx level, we don't need to involve higher layers. If we can't reproduce it at the httpx level, the bug is in how `HttpClientFactory` configures clients or how the Gateway uses them — and we've narrowed the search space.

### Decision 5: Test 5 (multi-worker) deferred or simplified

Instead of launching a full Gateway with `--workers 4`, Test 5 can simulate multi-worker behavior by spawning 4 `httpx.AsyncClient` instances in separate asyncio tasks (simulating independent event loops) or using `ProcessPoolExecutor`. This avoids the complexity of subprocess management while still demonstrating that independent clients do not coordinate their pools.

**Rationale:** Keeping all tests in-process (no subprocess) ensures they remain fast, debuggable, and CI-friendly. If evidence of a multi-worker issue is needed, a separate integration test can be added later.

## Risks / Trade-offs

- **[Risk] h2 protocol complexity** → **Mitigation**: Write a unit test for `EphemeralHttp2Server` itself (verify it responds correctly to a single httpx request) before using it in stress tests.
- **[Risk] OS TCP inspection not available in CI** → **Mitigation**: Make OS-level metrics optional (`os_tcp_established: int | None`). Server counters and httpx trace are sufficient for diagnosis.
- **[Risk] Flaky tests due to timing sensitivity** → **Mitigation**: Use generous timeouts (pool_timeout=15s, response delays ≥2s) and assert on error TYPE distributions rather than exact counts. Tests assert invariants ("no LocalProtocolError when max_connections is sufficient"), not exact performance.
- **[Risk] `return_exceptions=True` + `httpx.HTTPError` subclasses** → **Mitigation**: Classify exceptions explicitly by type in `MetricsCollector.stop()`, not by message string matching.
- **[Trade-off] Tests are not unit-test fast (~5-15s each)** → Accepted because they exercise the real network stack. Mark with `@pytest.mark.slow` and exclude from pre-commit hooks. Total suite: ~60-90s.
