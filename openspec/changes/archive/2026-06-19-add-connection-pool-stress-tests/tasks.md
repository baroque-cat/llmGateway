## 1. Git & Environment

- [x] 1.1 Create a new git branch for this change: `git checkout -b add-connection-pool-stress-tests`
- [x] 1.2 Run the full test suite to establish a passing baseline: `poetry run pytest tests/ -m "not slow" && poetry run pyright && poetry run ruff check src/ tests/`

## 2. Infrastructure: Ephemeral HTTP/2 Server

Reference: `specs/stress-test-infra/spec.md` — Requirements: EphemeralHttp2Server lifecycle, Configurable SETTINGS_MAX_CONCURRENT_STREAMS, Configurable response delay, Connection and stream counters. Design: `design.md` Decision 1 (raw asyncio + h2).

- [x] 2.1 Create `tests/stress/__init__.py` (empty)
- [x] 2.2 Create `tests/stress/ephemeral_api.py` with `EphemeralHttp2Server` class
  - `__init__(host="127.0.0.1", port=0, max_concurrent_streams=100, response_delay_ms=0, response_status=200, response_body=b'{"ok":true}')`
  - `start() -> str` — starts asyncio server, returns `"https://127.0.0.1:<port>"`
  - `stop()` — stops server, closes all connections
  - `stats` property — returns dict with `active_connections`, `total_connections`, `active_streams`, `peak_concurrent_streams`, `total_requests`, `errors`
  - Internal: `_handle_connection(reader, writer)` — h2 handshake, SETTINGS frame, request/response loop
  - Internal: `_send_response(conn, stream_id, headers, body)` — sends HTTP/2 response frames
  - Thread-safe counters via `asyncio.Lock`
- [x] 2.3 Verify h2 is importable (transitive dep of httpx[http2]): `python -c "import h2; print(h2.__version__)"`

## 3. Infrastructure: Metrics Collector

Reference: `specs/stress-test-infra/spec.md` — Requirement: MetricsCollector aggregates from multiple sources. Design: `design.md` Decision 2 (3-source metrics).

- [x] 3.1 Create `tests/stress/metrics.py` with `ConnectionMetrics` dataclass and `MetricsCollector` class
  - `ConnectionMetrics` fields: `server_peak_connections`, `server_peak_streams`, `server_total_requests`, `client_connections_created`, `client_connections_closed`, `os_tcp_established`, `local_protocol_errors`, `pool_timeout_errors`, `connect_errors`, `read_timeout_errors`, `other_errors`, `total_duration_sec`, `p50_latency_sec`, `p99_latency_sec`
  - `MetricsCollector.__init__(server, trace_enabled=True)`
  - `trace_handler(event)` — httpx trace callback, tracks connection/request lifecycle
  - `start()`, `stop() -> ConnectionMetrics` — aggregates errors by `isinstance()` type
  - `_read_os_tcp_stats() -> int | None` — reads `/proc/net/tcp` on Linux, returns `None` otherwise

## 4. Infrastructure: Test Fixtures

Reference: `design.md` Decision 3 (session-scoped factory).

- [x] 4.1 Create `tests/stress/conftest.py` with:
  - `http2_server_factory` — session-scoped async fixture, factory pattern with cleanup list
  - `fast_server` — function-scoped fixture: `max_concurrent_streams=100`, `response_delay_ms=0`
  - `slow_server` — function-scoped fixture: `max_concurrent_streams=5`, `response_delay_ms=2000`
  - `collector_factory` — function-scoped fixture returning `MetricsCollector`

## 5. Implementation: Stress Test Scenarios

Reference: `specs/stress-test-scenarios/spec.md` — all 6 requirements. Design: `design.md` Decisions 4-5 (httpx-level isolation, multi-worker simplification).

- [x] 5.1 Create `tests/stress/test_stream_exhaustion.py` — Test 1
  - `test_requests_exceed_stream_limit`: `max_connections=1`, `max_streams=5`, 20 concurrent requests, verify 5 max success + rest fail with `LocalProtocolError` or `PoolTimeout`
- [x] 5.2 Create `tests/stress/test_connection_growth.py` — Test 2
  - `test_six_connections_for_thirty_requests`: `max_connections=10`, `max_streams=5`, 30 concurrent requests, verify all 30 succeed, `client_connections_created >= 6`, `local_protocol_errors == 0`
- [x] 5.3 Create `tests/stress/test_pool_saturation.py` — Test 3
  - `test_pool_exhausted_with_long_responses`: `max_connections=3`, delay=10s, `pool_timeout=5.0`, 20 concurrent requests, verify `pool_timeout_errors > 0`, `local_protocol_errors == 0`
- [x] 5.4 Create `tests/stress/test_keepalive_churn.py` — Test 4
  - `test_connections_expire_between_sequential_requests`: `keepalive_expiry=5.0`, 20 sequential requests with 6s gaps, verify `client_connections_created >= 10`
- [x] 5.5 Create `tests/stress/test_multi_client.py` — Test 5
  - `test_two_clients_independent_connections`: Two `AsyncClient` instances, each `max_connections=5`, each sends 10 concurrent requests, verify `server.stats["peak_connections"] >= 2` and total connections ≤ 10
- [x] 5.6 Create `tests/stress/test_pool_recovery.py` — Test 6
  - `test_pool_recovers_after_load_reduction`: Phase 1: 50 concurrent (some fail ok), 30s quiet, Phase 2: 5 concurrent, verify all 5 succeed

## 6. Configuration: Pytest Markers

- [x] 6.1 Add `@pytest.mark.slow` decorator to all 8 test files in `tests/stress/`
- [x] 6.2 Add `slow` marker to `pyproject.toml` pytest config: `markers = ["slow: tests that exercise real network stack (deselect with '-m \"not slow\"')\"]`
- [x] 6.3 Verify marker filtering works: `poetry run pytest tests/stress/ -m slow --collect-only` shows all 17 tests

## 7. Quality Gates

- [x] 7.1 Run `poetry run black tests/stress/` — format all new files
- [x] 7.2 Run `poetry run ruff check tests/stress/` — lint all new files
- [x] 7.3 Run `poetry run pyright` — strict type checking (expect 0 errors in new files)
- [x] 7.4 Run full stress suite: `poetry run pytest tests/stress/ -m slow -v` — all 17 tests pass

## 8. Testing (Delegation)

Reference: `test-plan.md` Delegation Groups section — two groups: `stress-infra` (11 scenarios, 2 files) and `stress-scenarios` (6 scenarios, 6 files).

- [x] 8.1 Read `test-plan.md` Delegation Groups section
- [x] 8.2 Delegate group `stress-infra` to @Mr.Tester (scope: `tests/stress/test_ephemeral_server.py`, `tests/stress/test_metrics_collector.py`)
- [x] 8.3 Delegate group `stress-scenarios` to @Mr.Tester (scope: `tests/stress/test_stream_exhaustion.py`, `tests/stress/test_connection_growth.py`, `tests/stress/test_pool_saturation.py`, `tests/stress/test_keepalive_churn.py`, `tests/stress/test_multi_client.py`, `tests/stress/test_pool_recovery.py`)
- [x] 8.4 Review @Mr.Tester reports and fix any source-level bugs discovered in `ephemeral_api.py`, `metrics.py`, or `conftest.py`
- [x] 8.5 Re-delegate any groups affected by source fixes
- [x] 8.6 Verify all groups pass and coverage matches `test-plan.md` (17 scenarios, 17 test functions)
