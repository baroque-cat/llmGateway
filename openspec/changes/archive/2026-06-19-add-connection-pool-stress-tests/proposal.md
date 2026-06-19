## Why

Under multi-agent load (e.g., 10+ concurrent opencode agents using deepseek), the Conductor's httpx connection pool exhausts its HTTP/2 stream capacity, producing `LocalProtocolError: Max outbound streams is 128, 128 open`. The retry logic classifies this local infrastructure error as `NETWORK_ERROR` (server error), triggering cascading key penalization — ~50 valid keys burned in a single incident before restart. The current unit test suite mocks `httpx.AsyncClient` entirely, never exercising the real TCP/HTTP2 stack, so this class of pool-level defects is invisible to CI. We need controlled, reproducible stress tests with a real HTTP/2 server to prove whether httpx correctly manages connection pools under our `Limits` configuration, or whether the defect lies in net/http stack behavior.

## What Changes

- Add `tests/stress/ephemeral_api.py` — a minimal HTTP/2 test server (asyncio + h2) with configurable `SETTINGS_MAX_CONCURRENT_STREAMS`, response delay, and built-in connection/stream counters
- Add `tests/stress/metrics.py` — a `MetricsCollector` that aggregates connection metrics from three sources: the ephemeral server's counters, httpx trace events, and (optionally) OS TCP socket inspection
- Add 6 stress tests (`tests/stress/test_*.py`) that exercise real `httpx.AsyncClient` instances against the ephemeral server under controlled concurrency, latency, and connection limits
- No changes to production code in `src/`
- No new package dependencies — `h2` is already a transitive dependency of `httpx[http2]`

## Capabilities

### New Capabilities
- `stress-test-infra`: Ephemeral HTTP/2 test server (`EphemeralHttp2Server`) with configurable stream limits, response delay, connection counting; and `MetricsCollector` with multi-source metric aggregation.
- `stress-test-scenarios`: Six stress test cases covering stream exhaustion, connection growth, pool saturation, keep-alive churn, multi-worker connection count, and recovery after overload.

### Modified Capabilities
<!-- None — no production code or existing spec changes -->

## Impact

- New directory: `tests/stress/` with 8 files (~1200 lines total)
- No changes to `src/`, `config/`, `Dockerfile`, or `docker-compose.yml`
- No new dependencies required (h2 already present via httpx[http2])
- No database connection needed — tests run against ephemeral in-process server
- CI impact: tests run with `poetry run pytest tests/stress/` — expect ~5-15s per test, ~60-90s for full suite
