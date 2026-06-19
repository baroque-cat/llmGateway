# Test Plan: pool-error-isolation

## Coverage Map: Spec-to-Test Traceability

| # | Spec Capability | Requirement | Scenario | Test File | Test Name | Group |
|---|----------------|-------------|----------|-----------|-----------|-------|
| 1 | pool-error-isolation | Provider detects pool-level HTTP/2 protocol errors | Pool-saturated LocalProtocolError captured | `tests/unit/providers/test_base.py` | `test_local_protocol_error_maps_to_bad_request` | pool-error-classification |
| 2 | pool-error-isolation | Provider detects pool-level HTTP/2 protocol errors | Other RequestError subclasses unchanged | `tests/unit/providers/test_base.py` | `test_other_request_errors_still_map_to_network_error` | pool-error-classification |
| 3 | pool-error-isolation | Gateway handlers skip key penalization for pool errors | Full-stream handler skips penalty for BAD_REQUEST | `tests/unit/services/test_gateway_core.py` | `test_full_stream_skips_penalty_for_client_error` | pool-gateway |
| 4 | pool-error-isolation | Gateway handlers skip key penalization for pool errors | Retry handler aborts immediately for BAD_REQUEST | `tests/unit/services/test_gateway_core.py` | `test_retry_handler_aborts_for_client_error` | pool-gateway |
| 5 | pool-health-logging | Pool exposes health summary method | Health summary returns connection counts | `tests/unit/core/http2/test_transport.py` | `test_get_health_summary_connection_counts` | pool-health-summary |
| 6 | pool-health-logging | Pool exposes health summary method | Health summary returns protocol split | `tests/unit/core/http2/test_transport.py` | `test_get_health_summary_protocol_split` | pool-health-summary |
| 7 | pool-health-logging | Pool exposes health summary method | Health summary returns stream metrics | `tests/unit/core/http2/test_transport.py` | `test_get_health_summary_stream_metrics` | pool-health-summary |
| 8 | pool-health-logging | Pool exposes health summary method | Health summary returns queue depth | `tests/unit/core/http2/test_transport.py` | `test_get_health_summary_queue_depth` | pool-health-summary |
| 9 | pool-health-logging | Factory aggregates health summaries across all clients | Health summaries for all cached clients | `tests/unit/core/test_http_client_factory.py` | `test_get_pool_health_summary_all_clients` | pool-health-factory |
| 10 | pool-health-logging | Factory aggregates health summaries across all clients | Empty cache returns empty dict | `tests/unit/core/test_http_client_factory.py` | `test_get_pool_health_summary_empty_cache` | pool-health-factory |
| 11 | pool-health-logging | Gateway logs pool health periodically at INFO level | Health log line format | `tests/unit/services/test_gateway_core.py` | `test_pool_health_log_line_format` | pool-gateway |
| 12 | pool-health-logging | Gateway logs pool health periodically at INFO level | Health logging respects configured interval | `tests/unit/services/test_gateway_core.py` | `test_pool_health_log_respects_interval` | pool-gateway |
| 13 | pool-health-logging | Gateway logs pool health periodically at INFO level | Health logging disabled when interval is zero | `tests/unit/services/test_gateway_core.py` | `test_pool_health_log_disabled_when_interval_zero` | pool-gateway |
| 14 | pool-health-logging | Gateway logs pool health periodically at INFO level | Health logging interval configurable | `tests/unit/config/test_http_client_config.py` | `test_pool_health_log_interval_default` | pool-health-config |

## Delegation Groups

### Group 1: `pool-error-classification`
- **Scope:** `tests/unit/providers/test_base.py`
- **Description:** Tests for `_send_proxy_request()` error classification — verifying `httpx.LocalProtocolError` maps to `ErrorReason.BAD_REQUEST` (client error, no key penalty), while all other `httpx.RequestError` subclasses continue to map to `ErrorReason.NETWORK_ERROR`.
- **Coverage:** Scenarios 1, 2

### Group 2: `pool-health-summary`
- **Scope:** `tests/unit/core/http2/test_transport.py`
- **Description:** Tests for `CapacityAwareHttp2Pool.get_health_summary()` — verifying connection counts, protocol split (H2 vs H1), stream metrics, and queue depth in the returned dict.
- **Coverage:** Scenarios 5, 6, 7, 8

### Group 3: `pool-health-factory`
- **Scope:** `tests/unit/core/test_http_client_factory.py`
- **Description:** Tests for `HttpClientFactory.get_pool_health_summary()` — verifying aggregation across all cached clients and empty-cache behavior.
- **Coverage:** Scenarios 9, 10

### Group 4: `pool-gateway`
- **Scope:** `tests/unit/services/test_gateway_core.py`
- **Description:** Tests for gateway handler behavior with pool errors (full-stream penalty skip, retry-handler abort) and the `_pool_health_log_loop` background task (log format, interval respect, zero-disabled).
- **Coverage:** Scenarios 3, 4, 11, 12, 13

### Group 5: `pool-health-config`
- **Scope:** `tests/unit/config/test_http_client_config.py`
- **Description:** Test for Pydantic model validation of the new `pool_health_log_interval_sec` field on `HttpClientConfig` — default value of 60 when not specified.
- **Coverage:** Scenario 14

## Test Modifications

### New Tests (to be created)

| # | File | Test Name | Reason |
|---|------|-----------|--------|
| 1 | `tests/unit/providers/test_base.py` | `test_local_protocol_error_maps_to_bad_request` | New behavior: `httpx.LocalProtocolError` → `ErrorReason.BAD_REQUEST` with detail string `" — connection pool saturated (all HTTP/2 streams in use)"` and synthetic 503 response. |
| 2 | `tests/unit/providers/test_base.py` | `test_other_request_errors_still_map_to_network_error` | Regression guard: all other `httpx.RequestError` subclasses (`PoolTimeout`, `ConnectError`, `RemoteProtocolError`, `ReadTimeout`, `WriteTimeout`, `ConnectTimeout`, plain `RequestError`) still map to `ErrorReason.NETWORK_ERROR`. |
| 3 | `tests/unit/services/test_gateway_core.py` | `test_full_stream_skips_penalty_for_client_error` | New behavior: `_handle_full_stream_request()` receives `CheckResult` with `error_reason.is_client_error() == True` → forwards error to client without calling `_report_key_failure()` or `cache.remove_key_from_pool()`. |
| 4 | `tests/unit/services/test_gateway_core.py` | `test_retry_handler_aborts_for_client_error` | New behavior: `_handle_buffered_retryable_request()` receives `CheckResult` with `error_reason.is_client_error() == True` → immediately aborts retry loop and forwards error without consuming `server_error_attempts` or `key_error_attempts`. |
| 5 | `tests/unit/core/http2/test_transport.py` | `test_get_health_summary_connection_counts` | New method: `get_health_summary()` returns `total_connections`, `active_connections`, `idle_connections` as non-negative ints with `total == active + idle`. |
| 6 | `tests/unit/core/http2/test_transport.py` | `test_get_health_summary_protocol_split` | New method: `get_health_summary()` returns `h2_connections` and `h1_connections` counting connections by protocol. |
| 7 | `tests/unit/core/http2/test_transport.py` | `test_get_health_summary_stream_metrics` | New method: `get_health_summary()` returns `active_h2_streams` and `max_h2_stream_capacity` summing across H2 connections. |
| 8 | `tests/unit/core/http2/test_transport.py` | `test_get_health_summary_queue_depth` | New method: `get_health_summary()` returns `queued_requests` with count of requests awaiting assignment. |
| 9 | `tests/unit/core/test_http_client_factory.py` | `test_get_pool_health_summary_all_clients` | New method: `get_pool_health_summary()` returns `dict[str, dict]` with one entry per key in `_clients`, each being a pool health summary dict. |
| 10 | `tests/unit/core/test_http_client_factory.py` | `test_get_pool_health_summary_empty_cache` | Edge case: `get_pool_health_summary()` returns `{}` when no clients are cached. |
| 11 | `tests/unit/services/test_gateway_core.py` | `test_pool_health_log_line_format` | New behavior: `_pool_health_log_loop` emits log lines matching `HTTP_POOL_HEALTH | <key> | conns: <total> total (<active> active, <idle> idle) | proto: <h2> H2 / <h1> H1 | streams: <active> active / <max> max_capacity | queued: <queued>`. |
| 12 | `tests/unit/services/test_gateway_core.py` | `test_pool_health_log_respects_interval` | Timing test: background task respects `pool_health_log_interval_sec=N` (uses `asyncio.sleep(N)` between iterations). |
| 13 | `tests/unit/services/test_gateway_core.py` | `test_pool_health_log_disabled_when_interval_zero` | Disable test: when `pool_health_log_interval_sec=0`, the background task is NOT started and no health log lines are emitted. |
| 14 | `tests/unit/config/test_http_client_config.py` | `test_pool_health_log_interval_default` | Pydantic default: `HttpClientConfig()` has `pool_health_log_interval_sec=60` by default. |

### Existing Tests That Do NOT Need Modification
- `tests/unit/providers/test_base.py::test_send_proxy_request_network_error_returns_body_none` — uses a plain `httpx.RequestError`, not `LocalProtocolError`. Adds coverage for the unchanged else-branch. No modification needed.
- All existing `test_send_proxy_request_*` tests — they test 200, 400, non-matching error_parsing rules, debug_mode, aread failure. None exercise `LocalProtocolError`. No modification needed.
- All existing `TestCapacityAwareHttp2Pool` tests in `tests/unit/core/http2/test_transport.py` — they test assignment, creation, capacity callback. The new `get_health_summary()` tests are additive, not replacements.
- All existing `tests/unit/core/test_http_client_factory.py` tests — they test cache keys, client creation, close_all. The new `get_pool_health_summary()` tests are additive.
- All existing gateway handler tests — they test standard success/failure paths. The new client-error-handler tests verify a specific path that depends on `is_client_error()` returning True for `ErrorReason.BAD_REQUEST`.

## Risks Coverage

The following risks from `design.md` are addressed by dedicated test coverage:

| # | Risk | Mitigation Test | Test File |
|---|------|-----------------|-----------|
| R1 | **`BAD_REQUEST` semantics imprecise** — operators see `BAD_REQUEST` for pool saturation | Verify the error_message detail string `" — connection pool saturated (all HTTP/2 streams in use)"` is present in the log and CheckResult. | `test_local_protocol_error_maps_to_bad_request` (Scenario #1) |
| R2 | **Other `httpx.LocalProtocolError` sources** — future httpx non-pool sources bypass key penalization | Regression test that `RemoteProtocolError`, `PoolTimeout`, `ConnectError`, `ReadTimeout`, `WriteTimeout`, `ConnectTimeout`, and plain `RequestError` still map to `ErrorReason.NETWORK_ERROR`. | `test_other_request_errors_still_map_to_network_error` (Scenario #2) |
| R3 | **Health logging accesses private httpx attributes** — `client._transport` private API | Test coverage of `get_pool_health_summary()` validates the contract between `HttpClientFactory`, the transport, and the pool. | `test_get_pool_health_summary_all_clients` (Scenario #9) |
| R4 | **`_pool_health_log_loop` crash silently terminates logging** | Verify the `except Exception` handler prevents crash propagation. Failed iteration is logged at ERROR level and the next interval retries. | `test_pool_health_log_respects_interval` (Scenario #12) — test that a failing `get_pool_health_summary` in one iteration does not stop the loop |
| R5 | **Health logging creates noise at high client counts** | Verify log format contains one line per cached client per interval and handles multiple cached clients without errors. | `test_pool_health_log_line_format` (Scenario #11) — test with multiple cached clients to verify format per-key output |

## Execution Order

Groups can execute in parallel since they target independent test files:

```
pool-error-classification ──┐
pool-health-summary ────────┤
pool-health-factory ────────┼── parallel
pool-gateway ───────────────┤
pool-health-config ─────────┘
```

## Test Framework & Conventions

- **Framework:** pytest ≥9.0 with `pytest-asyncio` (strict async mode)
- **Mocking:** `unittest.mock` (`MagicMock`, `AsyncMock`, `patch`) — no `pytest-mock`
- **Async tests:** `@pytest.mark.asyncio` + `async def`
- **Test classes:** `PascalCase` (`TestLocalProtocolErrorClassification`, `TestPoolHealthSummary`, etc.)
- **Test functions:** `snake_case` with descriptive names
- **Imports:** Absolute imports only (`from src.core.constants import ErrorReason`)
- **Code style:** Black (line length 88, double quotes), ruff with project rules

### Key Test Construction Patterns

**For `test_local_protocol_error_maps_to_bad_request` (Scenario #1):**
```python
# Use MockAIBaseProvider from existing test class TestSendProxyRequestChangedContract
# Mock client.send to raise httpx.LocalProtocolError("All streams busy")
# Assert CheckResult.error_reason == ErrorReason.BAD_REQUEST
# Assert " — connection pool saturated" in CheckResult.error_message
# Assert synthetic response has status_code == 503
# Assert body_bytes is None
```

**For `test_other_request_errors_still_map_to_network_error` (Scenario #2):**
```python
# Parameterized test over: PoolTimeout, ConnectError, RemoteProtocolError,
#   ReadTimeout, WriteTimeout, ConnectTimeout, RequestError
# Each must result in ErrorReason.NETWORK_ERROR
```

**For `test_full_stream_skips_penalty_for_client_error` (Scenario #3):**
```python
# Build request mock with provider, cache, http_factory
# Patch _send_proxy_request to return CheckResult.fail(ErrorReason.BAD_REQUEST)
# Assert response is forwarded (not a 503 JSONResponse)
# Assert cache.remove_key_from_pool NOT called
```

**For `test_retry_handler_aborts_for_client_error` (Scenario #4):**
```python
# Build request mock with retry enabled
# Patch _send_proxy_request to return CheckResult.fail(ErrorReason.BAD_REQUEST)
# Assert retry loop does NOT execute second iteration
# Assert server_error_attempts / key_error_attempts counters NOT advanced
# Assert response forwarded to client without JSONResponse(503)
```

**For `test_get_health_summary_connection_counts` (Scenario #5):**
```python
# Create pool with multiple mock connections (some active, some idle)
# Assert summary["total_connections"] == len(pool._connections)
# Assert summary["total_connections"] == summary["active_connections"] + summary["idle_connections"]
# All values are int >= 0
```

**For `test_get_health_summary_protocol_split` (Scenario #6):**
```python
# Create pool with an H2 connection and an H1 connection
# Assert summary["h2_connections"] == 1 and summary["h1_connections"] == 1
```

**For `test_get_health_summary_stream_metrics` (Scenario #7):**
```python
# Create pool with H2 connections, query stream stats via conn._connection
# Assert summary["active_h2_streams"] >= 0 and summary["max_h2_stream_capacity"] > 0
# Verify stream metrics are sums across all H2 connections
```

**For `test_get_health_summary_queue_depth` (Scenario #8):**
```python
# Create pool with queued pool requests in pool._requests
# Assert summary["queued_requests"] matches count of is_queued()==True requests
```

**For pool health log tests (Scenarios #11-13):**
```python
# Use caplog fixture to capture INFO-level log output
# Patch HttpClientFactory.get_pool_health_summary to return controlled dicts
# Verify log line format with regex matching the spec format
# For interval test: use asyncio.sleep mocking or fast interval
# For zero-disabled: assert background task NOT started
```

**For config test (Scenario #14):**
```python
# HttpClientConfig() → assert pool_health_log_interval_sec == 60
# HttpClientConfig(pool_health_log_interval_sec=30) → assert == 30
# Optional: HttpClientConfig(pool_health_log_interval_sec=0) → assert == 0 (disabled)
```
