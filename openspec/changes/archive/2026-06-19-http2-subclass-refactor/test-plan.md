# QA Strategy & Test Plan

## Coverage Map

| Spec Capability | Requirement | Scenario | Test File | Test Name | Group |
|---|---|---|---|---|---|
| http2-nonblocking-semaphore | Semaphore exposes atomic acquire_nowait() | Successful non-blocking acquire | tests/unit/core/http2/test_semaphore.py | test_acquire_nowait_success | core-http2-unit |
| http2-nonblocking-semaphore | Semaphore exposes atomic acquire_nowait() | Failed non-blocking acquire | tests/unit/core/http2/test_semaphore.py | test_acquire_nowait_full | core-http2-unit |
| http2-nonblocking-semaphore | Semaphore exposes atomic acquire_nowait() | Asyncio backend | tests/unit/core/http2/test_semaphore.py | test_acquire_nowait_asyncio_backend | core-http2-unit |
| http2-nonblocking-semaphore | Semaphore exposes atomic acquire_nowait() | Trio backend | tests/unit/core/http2/test_semaphore.py | test_acquire_nowait_trio_backend | core-http2-unit |
| http2-nonblocking-semaphore | Semaphore is a subclass, not a monkey-patch | Backward compatible | tests/unit/core/http2/test_semaphore.py | test_inherits_acquire_release_unchanged | core-http2-unit |
| http2-stream-desync-fix | Connection cleans up h2 stream state after asyncio cancellation | Normal stream close (no cancellation) | tests/unit/core/http2/test_h2_connection.py | test_response_closed_normal_clean_stream | core-http2-unit |
| http2-stream-desync-fix | Connection cleans up h2 stream state after asyncio cancellation | Cancelled stream (stream not in _closed_streams) | tests/unit/core/http2/test_h2_connection.py | test_response_closed_cancelled_stream_reset | core-http2-unit |
| http2-stream-desync-fix | Connection cleans up h2 stream state after asyncio cancellation | Semaphore release is conditional | tests/unit/core/http2/test_h2_connection.py | test_response_closed_conditional_release | core-http2-unit |
| http2-stream-desync-fix | Connection cleans up h2 stream state after asyncio cancellation | Connection closes when stream was reset | tests/unit/core/http2/test_h2_connection.py | test_response_closed_reset_closes_connection | core-http2-unit |
| http2-stream-desync-fix | Connection tracks server-closed streams | Server closes stream cleanly | tests/unit/core/http2/test_h2_connection.py | test_receive_events_tracks_closed_stream | core-http2-unit |
| http2-stream-desync-fix | Connection advertises H2 stream capacity | Connection is full | tests/unit/core/http2/test_h2_connection.py | test_is_available_returns_false_when_full | core-http2-unit |
| http2-stream-desync-fix | Connection advertises H2 stream capacity | Connection has room | tests/unit/core/http2/test_h2_connection.py | test_is_available_returns_true_when_room | core-http2-unit |
| http2-stream-desync-fix | Connection signals pool on SETTINGS change | Server increases stream limit | tests/unit/core/http2/test_h2_connection.py | test_settings_change_calls_on_capacity_update | core-http2-unit |
| http2-stream-desync-fix | Connection signals pool on SETTINGS change | No callback configured | tests/unit/core/http2/test_h2_connection.py | test_settings_change_no_callback_no_error | core-http2-unit |
| http2-stream-desync-fix | Connection returns max concurrent requests | Connection initialized | tests/unit/core/http2/test_h2_connection.py | test_max_concurrent_requests_initialized | core-http2-unit |
| http2-stream-desync-fix | Connection returns max concurrent requests | Connection not yet initialized | tests/unit/core/http2/test_h2_connection.py | test_max_concurrent_requests_not_initialized | core-http2-unit |
| http2-capacity-aware-pool | Transport opens new TCP connections when H2 streams are full | Existing connection has available streams | tests/unit/core/http2/test_transport.py | test_assign_to_available_connection | core-http2-unit |
| http2-capacity-aware-pool | Transport opens new TCP connections when H2 streams are full | All connections are full, pool has room | tests/unit/core/http2/test_transport.py | test_create_new_connection_when_full | core-http2-unit |
| http2-capacity-aware-pool | Transport opens new TCP connections when H2 streams are full | Pool is also full | tests/unit/core/http2/test_transport.py | test_close_idle_when_pool_full | core-http2-unit |
| http2-capacity-aware-pool | Transport tracks requests assigned to each connection | Request assigned to connection | tests/unit/core/http2/test_transport.py | test_connection_request_count_incremented | core-http2-unit |
| http2-capacity-aware-pool | Transport tracks requests assigned to each connection | Initial count | tests/unit/core/http2/test_transport.py | test_connection_request_count_initial_state | core-http2-unit |
| http2-capacity-aware-pool | Transport queries connection capacity | Connection supports max_concurrent_requests() | tests/unit/core/http2/test_transport.py | test_max_concurrent_requests_supported | core-http2-unit |
| http2-capacity-aware-pool | Transport queries connection capacity | Connection does not support max_concurrent_requests() | tests/unit/core/http2/test_transport.py | test_max_concurrent_requests_fallback | core-http2-unit |
| http2-capacity-aware-pool | Transport wires on_capacity_update callback | Connection created | tests/unit/core/http2/test_transport.py | test_create_connection_wires_callback | core-http2-unit |
| http2-capacity-aware-pool | Capacity callback triggers request reassignment | Connection signals capacity change | tests/unit/core/http2/test_transport.py | test_capacity_updated_reassigns_requests | core-http2-unit |
| http2-capacity-aware-pool | Transport is a pluggable httpx transport | httpx uses custom transport | tests/unit/core/http2/test_transport.py | test_transport_pluggable_into_httpx | core-http2-unit |
| http2-capacity-aware-pool | CapacityAwareHTTPConnection creates FixedHTTP2Connection | HTTP/2 negotiated | tests/unit/core/http2/test_connection.py | test_creates_fixed_h2_on_alpn | core-http2-unit |
| http2-capacity-aware-pool | CapacityAwareHTTPConnection creates FixedHTTP2Connection | HTTP/1.1 negotiated | tests/unit/core/http2/test_connection.py | test_creates_http11_on_no_alpn | core-http2-unit |

## Delegation Groups

### Group: core-http2-unit

**Scope:** `tests/unit/core/http2/`

| Test File | Scenarios | Action |
|---|---|---|
| `tests/unit/core/http2/test_semaphore.py` | 5 | NEW |
| `tests/unit/core/http2/test_h2_connection.py` | 11 | NEW |
| `tests/unit/core/http2/test_connection.py` | 2 | NEW |
| `tests/unit/core/http2/test_transport.py` | 10 | NEW |

### Group: stress-tests-regression

**Scope:** `tests/stress/`

| Test File | Scenarios | Action |
|---|---|---|
| `tests/stress/test_connection_growth.py` | 1 | VERIFY |
| `tests/stress/test_pool_saturation.py` | 1 | VERIFY |
| `tests/stress/test_pool_recovery.py` | 1 | VERIFY |
| `tests/stress/test_stream_exhaustion.py` | 1 | VERIFY |
| `tests/stress/test_keepalive_churn.py` | 1 | VERIFY |
| `tests/stress/test_multi_client.py` | 1 | VERIFY |
| `tests/stress/test_ephemeral_server.py` | 6 | VERIFY |

### Group: integration-tests

**Scope:** `tests/unit/core/test_http_client_factory.py` (new), `tests/integration/`

| Test File | Scenarios | Action |
|---|---|---|
| `tests/unit/core/test_http_client_factory.py` | 2 | NEW (verify transport injection) |
| `tests/integration/` (existing) | All | VERIFY (no regressions) |

## Test Modifications

| File | Change | Reason |
|---|---|---|
| `tests/stress/conftest.py` | Remove `apply_patch()` call at line 19 | Patch is replaced by transport injection; stress tests use `HttpClientFactory` |
| `tests/stress/test_stream_desync_patch.py` | Delete file (replaced by `tests/unit/core/http2/test_h2_connection.py`) | Desync fix is now in `FixedHTTP2Connection`, tested via unit tests rather than integration-style raw httpcore test |
| `tests/stress/test_connection_growth.py` | No logic change — assertions may need update if transport timing differs | Described in design.md Risks: "Stress test timing changes" |
| `main.py` | Remove `apply_patch()` call at line 23 | Patch no longer applied at module level |

## Risks & Edge Cases

- **[Risk] httpcore upgrade breaks subclass** → Unit tests use frozen mocks matching httpcore 1.0.9. CI version check `assert httpcore.__version__ == "1.0.9"` catches drift before it reaches tests.
- **[Risk] Stress test timing changes** → Stress tests use range assertions (`>= 2`, `> 0`, `< 30`), not exact values. VERIFY action confirms all pass after migration. If timing differences cause failures, assertions can be relaxed within documented acceptable ranges.
- **[Risk] `uv.lock` and `poetry.lock` diverge** → Both lockfiles resolve httpcore==1.0.9. Explicit pin in `pyproject.toml` prevents divergence. CI checks both for httpcore version.
- **[Risk] `FixedHTTP2Connection.handle_async_request` goes stale** → The copied method is version-guarded by the frozen httpcore pin. When httpcore merges PR #1088, the entire class is removed. Unit tests lock behavior to httpcore 1.0.9.
