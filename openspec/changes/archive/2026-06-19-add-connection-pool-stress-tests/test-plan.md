# QA Strategy & Test Plan

## Coverage Map

| Spec Capability | Requirement | Scenario | Test File | Test Name | Group |
|---|---|---|---|---|---|
| `stress-test-infra` | EphemeralHttp2Server lifecycle | Server starts on random port | `tests/stress/test_ephemeral_server.py` | `test_server_starts_on_random_port` | `stress-infra` |
| `stress-test-infra` | EphemeralHttp2Server lifecycle | Server responds to single HTTP/2 request | `tests/stress/test_ephemeral_server.py` | `test_server_responds_to_single_request` | `stress-infra` |
| `stress-test-infra` | EphemeralHttp2Server lifecycle | Server stops cleanly | `tests/stress/test_ephemeral_server.py` | `test_server_stops_cleanly` | `stress-infra` |
| `stress-test-infra` | Configurable SETTINGS_MAX_CONCURRENT_STREAMS | Client observes the stream limit | `tests/stress/test_ephemeral_server.py` | `test_client_observes_stream_limit` | `stress-infra` |
| `stress-test-infra` | Configurable response delay | Response arrives after configured delay | `tests/stress/test_ephemeral_server.py` | `test_response_arrives_after_delay` | `stress-infra` |
| `stress-test-infra` | Connection and stream counters | Metrics reflect concurrent state | `tests/stress/test_ephemeral_server.py` | `test_metrics_reflect_concurrent_state` | `stress-infra` |
| `stress-test-infra` | Connection and stream counters | Peak stream count is tracked | `tests/stress/test_ephemeral_server.py` | `test_peak_stream_count_tracked` | `stress-infra` |
| `stress-test-infra` | Connection and stream counters | Total connection count is cumulative | `tests/stress/test_ephemeral_server.py` | `test_total_connection_count_cumulative` | `stress-infra` |
| `stress-test-infra` | MetricsCollector aggregates from multiple sources | httpx trace captures connection creation | `tests/stress/test_metrics_collector.py` | `test_trace_captures_connection_creation` | `stress-infra` |
| `stress-test-infra` | MetricsCollector aggregates from multiple sources | Error classification by exception type | `tests/stress/test_metrics_collector.py` | `test_error_classification_by_type` | `stress-infra` |
| `stress-test-infra` | MetricsCollector aggregates from multiple sources | OS TCP metric is optional | `tests/stress/test_metrics_collector.py` | `test_os_tcp_metric_optional` | `stress-infra` |
| `stress-test-scenarios` | Stream exhaustion reproduces LocalProtocolError | Requests exceed stream limit on single connection | `tests/stress/test_stream_exhaustion.py` | `test_requests_exceed_stream_limit` | `stress-scenarios` |
| `stress-test-scenarios` | httpx opens new connections when streams are exhausted | Six connections needed for 30 requests with 5-stream limit | `tests/stress/test_connection_growth.py` | `test_six_connections_for_thirty_requests` | `stress-scenarios` |
| `stress-test-scenarios` | Pool saturation produces PoolTimeout, not LocalProtocolError | Pool exhausted with long responses | `tests/stress/test_pool_saturation.py` | `test_pool_exhausted_with_long_responses` | `stress-scenarios` |
| `stress-test-scenarios` | Short keep-alive expiry causes connection churn | Connections expire between sequential requests | `tests/stress/test_keepalive_churn.py` | `test_connections_expire_between_sequential_requests` | `stress-scenarios` |
| `stress-test-scenarios` | Multiple independent clients do not share pools | Two clients create independent connections | `tests/stress/test_multi_client.py` | `test_two_clients_independent_connections` | `stress-scenarios` |
| `stress-test-scenarios` | Recovery after connection pool overload | Pool recovers after load reduction | `tests/stress/test_pool_recovery.py` | `test_pool_recovers_after_load_reduction` | `stress-scenarios` |

**Totals:** 2 spec capabilities, 11 requirements, 17 scenarios, 8 test files, 17 test functions, 2 groups.

## Delegation Groups

### Group: `stress-infra`

**Scope:** `tests/stress/test_ephemeral_server.py`, `tests/stress/test_metrics_collector.py`

| Test File | Scenarios | Action |
|---|---|---|
| `tests/stress/test_ephemeral_server.py` | 8 | NEW |
| `tests/stress/test_metrics_collector.py` | 3 | NEW |

### Group: `stress-scenarios`

**Scope:** `tests/stress/test_stream_exhaustion.py`, `tests/stress/test_connection_growth.py`, `tests/stress/test_pool_saturation.py`, `tests/stress/test_keepalive_churn.py`, `tests/stress/test_multi_client.py`, `tests/stress/test_pool_recovery.py`

| Test File | Scenarios | Action |
|---|---|---|
| `tests/stress/test_stream_exhaustion.py` | 1 | NEW |
| `tests/stress/test_connection_growth.py` | 1 | NEW |
| `tests/stress/test_pool_saturation.py` | 1 | NEW |
| `tests/stress/test_keepalive_churn.py` | 1 | NEW |
| `tests/stress/test_multi_client.py` | 1 | NEW |
| `tests/stress/test_pool_recovery.py` | 1 | NEW |

## Test Modifications

**No existing tests require modification.** The `tests/stress/` directory does not yet exist. All 8 test files are NEW. No existing test files under `tests/unit/`, `tests/integration/`, or `tests/e2e/` are touched by this change — the stress tests are purely additive and exercise the real `httpx.AsyncClient` against an ephemeral in-process HTTP/2 server, without depending on or altering any existing test fixtures or production code.

## Risks & Edge Cases

- **[Risk] h2 protocol complexity** → Dedicated unit test `test_server_responds_to_single_request` in `tests/stress/test_ephemeral_server.py` validates that `EphemeralHttp2Server` correctly handles the full HTTP/2 handshake, SETTINGS frame exchange, request parsing, and response framing with a real `httpx.AsyncClient(http2=True)` before the stress scenarios depend on it. This is the first scenario under the EphemeralHttp2Server lifecycle requirement.

- **[Risk] OS TCP inspection not available in CI** → `test_os_tcp_metric_optional` in `tests/stress/test_metrics_collector.py` verifies that `MetricsCollector` returns `os_tcp_established=None` on platforms without `/proc/net/tcp` (macOS, Windows, non-Linux CI runners) rather than raising an error. The stress scenario tests rely on server counters and httpx trace events as the two primary metric sources; OS TCP inspection is never a hard dependency.

- **[Risk] Flaky tests due to timing sensitivity** → All scenario tests use generous timeouts (`response_delay_ms=2000`, `pool_timeout` values ≥5s, quiet-period intervals ≥30s per the Recovery scenario). Assertions target error **type** distributions (e.g., `local_protocol_errors > 0`, `pool_timeout_errors > 0`) rather than exact integer counts. Tests assert invariants ("no `LocalProtocolError` when `max_connections` is sufficient") rather than exact performance numbers, making them resilient to CI-vs-local timing variance.

- **[Risk] `return_exceptions=True` + `httpx.HTTPError` subclasses causing misclassification** → `test_error_classification_by_type` in `tests/stress/test_metrics_collector.py` verifies that `MetricsCollector.stop()` explicitly classifies exceptions by `isinstance()` checks against `httpx.LocalProtocolError`, `httpx.PoolTimeout`, and base `httpx.HTTPError`, never by string-matching on error messages. This is the second scenario under the MetricsCollector requirement.

- **[Trade-off] Tests are not unit-test fast (~5–15s each, ~60–90s total suite)** → All 8 test files (and any future stress tests) SHALL be decorated with `@pytest.mark.slow` and excluded from pre-commit hooks and fast-path CI checks via `pytest.ini_options.markers` and a `-m "not slow"` filter in the default test invocation. A dedicated CI step or manual trigger runs `poetry run pytest tests/stress/ -m slow` for the full suite.
