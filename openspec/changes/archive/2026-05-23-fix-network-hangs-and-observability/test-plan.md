# QA Strategy & Test Plan

> **Change:** fix-network-hangs-and-observability
> **Generated:** 2026-05-23
> **Framework:** pytest ≥9.0 + pytest-asyncio + pytest-cov
> **Mocking:** unittest.mock only (MagicMock, AsyncMock, patch)
> **Python:** 3.13+

---

## Coverage Map

| # | Spec Capability | Requirement | Scenario | Test File | Test Name | Group |
|---|---|---|---|---|---|---|
| 1 | request-lifecycle-timeout | Total request deadline enforced via asyncio.timeout | Timeout fires during retry loop | `tests/unit/services/test_gateway_timeout.py` | `test_timeout_fires_mid_retry_returns_504` | gateway-timeout |
| 2 | request-lifecycle-timeout | Total request deadline enforced via asyncio.timeout | Timeout does not fire for fast failure | `tests/unit/services/test_gateway_timeout.py` | `test_fast_failure_completes_without_timeout_trigger` | gateway-timeout |
| 3 | request-lifecycle-timeout | Total request deadline enforced via asyncio.timeout | Backoff sleeps are counted within the deadline | `tests/unit/services/test_gateway_timeout.py` | `test_backoff_sleeps_consume_deadline` | gateway-timeout |
| 4 | request-lifecycle-timeout | Total request deadline enforced via asyncio.timeout | Timeout exhaustion response includes structured data | `tests/unit/services/test_gateway_timeout.py` | `test_timeout_exhaustion_504_json_structure` | gateway-timeout |
| 5 | request-lifecycle-timeout | timeouts.total field in TimeoutConfig | Default total timeout is 600 seconds | `tests/unit/config/test_timeout_config.py` | `test_total_default_is_600` | config-timeout |
| 6 | request-lifecycle-timeout | timeouts.total field in TimeoutConfig | Custom total timeout from YAML | `tests/unit/config/test_timeout_config.py` | `test_total_from_yaml_custom_value` | config-timeout |
| 7 | http-client-pool-config | Global HTTP client pool configuration | Default pool limits applied | `tests/unit/core/test_http_client_factory.py` | `test_default_pool_limits_applied` | http-client-factory |
| 8 | http-client-pool-config | Global HTTP client pool configuration | Custom pool limits from YAML | `tests/unit/config/test_http_client_config.py` | `test_custom_pool_limits_from_yaml` | config-http-client |
| 9 | http-client-pool-config | Global HTTP client pool configuration | Pool limits apply to both Keeper and Gateway | `tests/unit/config/test_http_client_config.py` | `test_pool_limits_apply_to_keeper_and_gateway` | config-http-client |
| 10 | http-client-pool-config | HttpClientPoolConfig model | Pool config validates bounds | `tests/unit/config/test_http_client_config.py` | `test_pool_config_rejects_max_connections_zero` | config-http-client |
| 11 | http-client-pool-config | HttpClientConfig model | http2 can be disabled globally | `tests/unit/config/test_http_client_config.py` | `test_http2_disabled_globally` | config-http-client |
| 12 | http-client-pool-config | dedicated_http_client defaults to True | New provider gets dedicated client by default | `tests/unit/config/test_defaults.py` | `test_default_config_dedicated_http_client` (MODIFY) | config-defaults |
| 13 | http-client-pool-config | dedicated_http_client defaults to True | Explicit false still works | `tests/unit/core/test_http_client_factory.py` | `test_dedicated_false_still_shares_client` | http-client-factory |
| 14 | http-client-logging | Independent httpx and httpcore log level control | Default config silences httpx and httpcore | `tests/unit/config/test_logging_config_module.py` | `test_http_client_logging_defaults_silence_httpx_and_httpcore` | config-logging |
| 15 | http-client-logging | Independent httpx and httpcore log level control | httpcore_level debug enables HTTP/2 tracing | `tests/unit/config/test_logging_config_module.py` | `test_httpcore_debug_enables_http2_tracing` | config-logging |
| 16 | http-client-logging | Independent httpx and httpcore log level control | httpcore_level warning prevents noise at INFO | `tests/unit/config/test_logging_config_module.py` | `test_httpcore_warning_prevents_info_noise` | config-logging |
| 17 | http-client-logging | Enhanced network error logging format | ReadTimeout logged with detail | `tests/unit/providers/test_base.py` | `test_send_proxy_request_logs_readtimeout_with_detail` | provider-error-logging |
| 18 | http-client-logging | Enhanced network error logging format | RemoteProtocolError logged with detail | `tests/unit/providers/test_base.py` | `test_send_proxy_request_logs_remoteprotocolerror_with_detail` | provider-error-logging |
| 19 | http-client-logging | Enhanced network error logging format | PoolTimeout logged with detail | `tests/unit/providers/test_base.py` | `test_send_proxy_request_logs_pooltimeout_with_detail` | provider-error-logging |
| 20 | http-client-logging | Enhanced network error logging format | Unknown RequestError subtype logged without extra detail | `tests/unit/providers/test_base.py` | `test_send_proxy_request_logs_unknown_requesterror_without_extra_detail` | provider-error-logging |
| 21 | http-client-logging | Enhanced retry attempt logging | Retry failure log includes key and status | `tests/unit/services/test_gateway_timeout.py` | `test_retry_attempt_log_includes_key_id_and_status` | gateway-timeout |
| 22 | transparent-gateway-routing | Database query timeout via command_timeout | Default command_timeout is 30 seconds | `tests/unit/config/test_database_pool_config.py` | `test_command_timeout_default_30` | config-database |
| 23 | transparent-gateway-routing | Database query timeout via command_timeout | Query exceeding command_timeout raises exception | `tests/unit/db/test_init_db_pool_params.py` | `test_command_timeout_passed_to_create_pool` | database-timeout |
| 24 | transparent-gateway-routing | Database query timeout via command_timeout | VACUUM ANALYZE overrides command_timeout | `tests/unit/services/test_db_maintainer.py` | `test_vacuum_analyze_overrides_command_timeout` | database-timeout |
| 25 | transparent-gateway-routing | Gateway does not parse request bodies in full-stream path | Full-stream bypasses body parsing | `tests/unit/services/test_gateway_transparent_routing.py` | `test_full_stream_bypasses_body_parsing` | gateway-routing |
| 26 | transparent-gateway-routing | Full-stream mode is the default for all instances | Standard instance uses full stream | `tests/unit/services/test_gateway_transparent_routing.py` | `test_standard_instance_uses_full_stream` | gateway-routing |
| 27 | transparent-gateway-routing | Full-stream mode is the default for all instances | Debug mode forces buffered handling | `tests/unit/services/test_gateway_transparent_routing.py` | `test_debug_mode_forces_buffered_handler` | gateway-routing |
| 28 | transparent-gateway-routing | Full-stream mode is the default for all instances | Retry mode forces buffered handling | `tests/unit/services/test_gateway_transparent_routing.py` | `test_retry_mode_forces_buffered_handler_with_timeout` | gateway-routing |
| 29 | transparent-gateway-routing | Full-stream mode is the default for all instances | Network error logged with structured detail | (covered by rows 17–20) | — | provider-error-logging |
| 30 | transparent-gateway-routing | Gateway forwards requests without model validation | Unknown model forwarded transparently | `tests/unit/services/test_gateway_transparent_routing.py` | `test_unknown_model_forwarded_transparently` (VERIFY) | gateway-routing |
| 31 | transparent-gateway-routing | Gateway passes URL path verbatim to upstream | Compatible-mode path forwarded unchanged | `tests/unit/services/test_gateway_transparent_routing.py` | `test_compatible_mode_url_path_verbatim` | gateway-routing |

---

## Delegation Groups

### Group: config-timeout
**Scope:** New `TimeoutConfig.total` field schema validation and YAML loading.
**Target files:** `src/config/schemas.py::TimeoutConfig`

| Test File | Scenarios | Action |
|---|---|---|
| `tests/unit/config/test_timeout_config.py` | #5, #6 | **CREATE** — test `total` default (600.0), custom YAML, validation (gt=0), backward compatibility (old configs without `total` field) |

### Group: config-http-client
**Scope:** New `HttpClientPoolConfig` and `HttpClientConfig` Pydantic models; YAML loading integration.
**Target files:** `src/config/schemas.py` (new models)

| Test File | Scenarios | Action |
|---|---|---|
| `tests/unit/config/test_http_client_config.py` | #8, #9, #10, #11 | **CREATE** — test pool config defaults, validation (max_connections=0 rejected), http2 toggle, YAML loading with custom values, and integration check that both Keeper and Gateway factories read same config |

### Group: config-logging
**Scope:** New `HttpClientLoggingConfig` nested section in `LoggingConfig` and its application in `setup_logging()`.
**Target files:** `src/config/schemas.py` (new model), `src/config/logging_config.py::setup_logging()`

| Test File | Scenarios | Action |
|---|---|---|
| `tests/unit/config/test_logging_config_module.py` | #14, #15, #16 | **MODIFY** — add tests for: (a) default `http_client` section sets `httpx` and `httpcore` loggers to `WARNING`; (b) `httpcore_level: DEBUG` produces HTTP/2 tracing messages; (c) `httpcore_level: WARNING` overrides root `INFO` level for httpcore |

### Group: config-database
**Scope:** New `command_timeout` and `connect_timeout` fields on `DatabasePoolConfig`.
**Target files:** `src/config/schemas.py::DatabasePoolConfig`

| Test File | Scenarios | Action |
|---|---|---|
| `tests/unit/config/test_database_pool_config.py` | #22 | **MODIFY** — add tests: default `command_timeout=30.0`, default `connect_timeout=60.0`, custom values accepted, validation (gt=0 enforced), YAML backward compatibility (old configs without these fields) |

### Group: config-defaults
**Scope:** `dedicated_http_client` default changes from `False` → `True` in `ProviderConfig`, reflected in `defaults.py`.
**Target files:** `src/config/schemas.py::ProviderConfig`, `src/config/defaults.py`

| Test File | Scenarios | Action |
|---|---|---|
| `tests/unit/config/test_defaults.py` | #12 | **MODIFY** — update `test_default_config_dedicated_http_client()` (currently asserts `False`) to assert `True`; add a second test verifying that `ProviderConfig()` directly constructs with `dedicated_http_client=True` |

### Group: gateway-timeout
**Scope:** `asyncio.timeout()` wrapping the retry loop in `_handle_buffered_retryable_request()`. Includes structured 504 response, backoff counting, and enhanced retry attempt logging.
**Target files:** `src/services/gateway/gateway_service.py::_handle_buffered_retryable_request()`

| Test File | Scenarios | Action |
|---|---|---|
| `tests/unit/services/test_gateway_timeout.py` | #1, #2, #3, #4, #21 | **CREATE** — test: (a) mock `asyncio.sleep` to simulate slow upstream + backoff; inject `asyncio.timeout` via `unittest.mock.patch`; verify 504 JSONResponse with `error`, `attempts`, `last_error` fields; (b) fast-failure (immediate network errors) completes without `TimeoutError`; (c) `asyncio.sleep` during backoff consumes the deadline; (d) 504 body shape matches spec; (e) retry attempt warning log contains key ID and HTTP status code |

### Group: http-client-factory
**Scope:** `HttpClientFactory` applying pool limits, http2 toggle, and dedicated client behavior with new default.
**Target files:** `src/core/http_client_factory.py`

| Test File | Scenarios | Action |
|---|---|---|
| `tests/unit/core/test_http_client_factory.py` | #7, #13 | **MODIFY** — add tests: (a) factory creates clients with default pool limits (100/20/5.0); (b) factory creates clients with custom `HttpClientPoolConfig`; (c) when `dedicated_http_client=False`, sharing still works; (d) update existing factory construction to account for new `dedicated_http_client=True` default (providers now get dedicated clients by default); (e) http2 enabled/disabled per `HttpClientConfig.http2` |

### Group: provider-error-logging
**Scope:** Enhanced `except httpx.RequestError` handler in `AIBaseProvider._send_proxy_request()` — structured ERROR logs with type name, provider, URL, and human-readable detail.
**Target files:** `src/providers/base.py::_send_proxy_request()`

| Test File | Scenarios | Action |
|---|---|---|
| `tests/unit/providers/test_base.py` | #17, #18, #19, #20 | **MODIFY** — add tests: mock `client.send()` to raise `httpx.ReadTimeout`, `httpx.RemoteProtocolError`, `httpx.PoolTimeout`, and `httpx.CloseError` (unhandled subtype); use `self.assertLogs` or patch `src.providers.base.logger` to verify log message contains `[ExceptionTypeName]`, `provider=`, `url=`, and the expected human-readable detail string; verify the 3-tuple return value remains unchanged (synthetic 503 + `NETWORK_ERROR` CheckResult + `None` body) |

### Group: gateway-routing
**Scope:** Dispatch logic changes: full-stream as default, body parsing bypass, model transparency, URL path verbatim.
**Target files:** `src/services/gateway/gateway_service.py` (dispatch at ~line 900, `_handle_full_stream_request()`)

| Test File | Scenarios | Action |
|---|---|---|
| `tests/unit/services/test_gateway_transparent_routing.py` | #25, #26, #27, #28, #30, #31 | **MODIFY** — add tests: (a) `_handle_full_stream_request()` never calls `provider.parse_request_details()` with request body; (b) standard (no-retry, no-debug) instance dispatched to full-stream; (c) debug mode → buffered handler; (d) retry enabled → buffered handler with `asyncio.timeout` enforced; (e) URL path with `/compatible-mode/v1/chat/completions` is forwarded unchanged to upstream URL; (f) VERIFY existing `test_unknown_model_forwarded_transparently` still passes |

### Group: database-timeout
**Scope:** `command_timeout` and `connect_timeout` passed to `asyncpg.create_pool()`; VACUUM ANALYZE overrides command_timeout.
**Target files:** `src/db/database.py::init_db_pool()`, `src/services/db_maintainer.py`

| Test File | Scenarios | Action |
|---|---|---|
| `tests/unit/db/test_init_db_pool_params.py` | #23 | **MODIFY** — add test verifying `asyncpg.create_pool()` is called with `command_timeout=30.0` and `connect_timeout=60.0`; test custom values passed through from config |
| `tests/unit/services/test_db_maintainer.py` | #24 | **MODIFY** — add test: when `DatabaseMaintainer.run_conditional_vacuum()` runs VACUUM ANALYZE, the connection executes `SET statement_timeout = 0` before the VACUUM command; mock `conn.execute()` to verify call order |

---

## Test Modifications

### Files requiring changes to EXISTING tests

| File | Change | Reason |
|---|---|---|
| `tests/unit/config/test_defaults.py` | `test_default_config_dedicated_http_client()`: change assertion from `False` to `True` | `dedicated_http_client` default changes from `False` to `True` in `ProviderConfig` |
| `tests/unit/config/test_defaults.py` | `test_ut_ev03_hardcoded_constants_remain()`: may need to add `command_timeout` and `connect_timeout` to the list of recognized hardcoded DB pool defaults | New fields added to `DatabasePoolConfig` in `defaults.py` |
| `tests/unit/config/test_database_pool_config.py` | `TestDatabasePoolConfigDefaults`: add assertions for `command_timeout` and `connect_timeout` defaults | New fields on `DatabasePoolConfig` schema model |
| `tests/unit/config/test_database_pool_config.py` | `TestDatabasePoolConfigValidation`: add test for `command_timeout=0` rejection | New field validation (gt=0) |
| `tests/unit/db/test_init_db_pool_params.py` | Add assertions that `mock_create_pool` receives `command_timeout=30.0` and `connect_timeout=60.0` | `init_db_pool()` signature change adds timeout params |
| `tests/unit/core/test_http_client_factory.py` | `_make_provider_config()` helper and tests: default `dedicated_http_client` now `True` | ProviderConfig default change affects factory behavior |
| `tests/unit/core/test_http_client_factory.py` | Factory construction tests: add `HttpClientConfig` / pool limits to mock accessor | New `http_client` config section passed to factory |
| `tests/unit/services/test_db_maintainer.py` | Add test or modify existing VACUUM test to verify `SET statement_timeout = 0` call | VACUUM must override pool-level `command_timeout` |
| `tests/unit/providers/test_base.py` | Existing network error tests: verify log output format changed (from bare `"Upstream request failed..."` to structured format). Return value assertions (synthetic 503 + NETWORK_ERROR + None body) should still pass unchanged. | Enhanced error logging changes log message content but NOT return contract |
| `tests/unit/providers/test_provider_proxy_request.py` | Verify all existing `_send_proxy_request()` tests still pass (return tuple unchanged) | Enhanced logging should not affect return values |
| `tests/unit/services/test_gateway_core.py` | Tests for `_handle_buffered_retryable_request()`: may need `asyncio.timeout` mocking if tests run the retry loop long enough to trigger timeout. Check if mock responses are fast enough that default 600s timeout is irrelevant. | New `asyncio.timeout` wrapping changes control flow |
| `tests/integration/test_gateway_refactor.py` | Retry loop integration tests: same `asyncio.timeout` concern as unit tests. May need to patch `asyncio.timeout` with a longer duration or mock it entirely for integration tests that iterate many retries. | Retry loop now wrapped in `asyncio.timeout` |
| `tests/integration/test_gateway_retry_synergy.py` | Server-error + key-error transition tests: same `asyncio.timeout` concern. | Retry loop now wrapped in `asyncio.timeout` |
| `tests/unit/services/test_gateway_transparent_routing.py` | Dispatch routing tests: verify that full-stream default behavior for standard instances is correct; debug/retry still force buffered path. | Modeling scenarios #26, #27, #28 |
| `tests/unit/config/test_logging_config_module.py` | Existing `TestLoggingConfiguration` tests: add assertions that `setup_logging()` now also configures `httpx` and `httpcore` loggers. | New `http_client` logging section |
| `tests/unit/config/test_logging_config_module.py` | `test_setup_logging_applies_httpx_warning`: existing test (line ~462) for httpx logger silence; may need updating to use new config path. | httpx logger level now controlled via `logging.http_client.httpx_level` not hardcoded |

### New files to CREATE

| File | Scenarios Covered |
|---|---|
| `tests/unit/config/test_timeout_config.py` | #5, #6 |
| `tests/unit/config/test_http_client_config.py` | #8, #9, #10, #11 |
| `tests/unit/services/test_gateway_timeout.py` | #1, #2, #3, #4, #21 |

---

## Risks & Edge Cases

- **[Risk] asyncio.timeout fires mid-`client.send()` — could httpx leave a connection in bad state?**
  → **Mitigation:** `asyncio.CancelledError` triggers httpx internal cleanup. Next attempt uses a fresh request. The `except asyncio.TimeoutError` handler creates a synthetic 504, so no dangling connection leaks.
  → **Test:** Scenario #1 must verify that after `TimeoutError`, the handler returns a clean 504 without unclosed connections.

- **[Risk] Changing `dedicated_http_client` default from `False` to `True` increases TCP connection count per process.**
  → **Mitigation:** Each provider gets a private pool (100 connections each). Operators can set `dedicated_http_client: false` for shared-base-URL providers.
  → **Test:** Scenario #12 verifies the new default. Scenario #13 verifies explicit `false` still shares clients.

- **[Risk] `command_timeout=30` could kill legitimate slow queries during initial schema setup.**
  → **Mitigation:** Schema creation (`CREATE TABLE IF NOT EXISTS`) is idempotent and completes in <1s. `VACUUM ANALYZE` explicitly overrides via `SET statement_timeout = 0`.
  → **Test:** Scenario #24 verifies the VACUUM override.

- **[Trade-off] `total` timeout default (600s) applies to ALL providers unless overridden.**
  → With `connect=15`, `read=300`, `write=35`, `pool=35` (sum = 385s per attempt), 600s allows ~1.5 attempts. Operators wanting more retries must raise `total` proportionally.
  → **Test:** Scenario #1 verifies timeout fires at ~600s. Scenario #2 verifies it does NOT fire for fast failures.

- **[Risk] Backward compatibility — configs without new fields must load without error.**
  → All new fields (`TimeoutConfig.total`, `DatabasePoolConfig.command_timeout`, `HttpClientConfig`, `HttpClientLoggingConfig`) have defaults. Pydantic `default_factory` ensures omitted sections work.
  → **Test:** Scenario #5 (omitted `total` → 600.0), Scenario #7 (omitted `http_client` → default pool limits), Scenario #14 (omitted `http_client` logging → WARNING), Scenario #22 (omitted `command_timeout` → 30.0).

- **[Risk] `asyncio.timeout` behavior may interact unexpectedly with `asyncio.create_task()` fire-and-forget tasks inside the retry loop.**
  → `_report_key_failure()` and `cache.remove_key_from_pool()` are launched as background tasks within the timeout scope. If the timeout fires, these tasks may not complete. This is acceptable — the failed key has already been penalized in the local cache and the gateway returns 504 immediately.
  → **Test:** Scenario #1 should include verification that fire-and-forget tasks are launched but do not block the 504 response.

- **[Risk] log message format change could break production log alerting/monitoring that parses the old `"Upstream request failed with a network-level error"` string.**
  → **Mitigation:** This is an intentional improvement. The new format includes structured detail. Teams should update alerting rules to match the new pattern (`[ReadTimeout]`, `[RemoteProtocolError]`, `[PoolTimeout]`).
  → **Test:** Scenarios #17–20 verify the new log message format is correct.

- **[Risk] `httpcore` logger at `WARNING` by default may hide useful connection info during normal operation.**
  → **Mitigation:** This is a defensive default to prevent noise. Operators can set `logging.http_client.httpcore_level: "INFO"` or `"DEBUG"` if they need connection lifecycle visibility.
  → **Test:** Scenario #16 verifies that at `WARNING` level, httpcore does NOT emit INFO messages even when root logger is at INFO.

- **[Edge Case] `total` timeout is 0 or negative.**
  → Pydantic validation (`gt=0`) rejects at config load time. No runtime test needed beyond schema validation.
  → **Test:** Covered by `test_timeout_config.py` validation tests.

- **[Edge Case] `command_timeout` fires on `VACUUM ANALYZE` without the `SET statement_timeout = 0` override.**
  → If the `SET` command fails or is skipped, VACUUM could be killed mid-operation. The dead-tuple metrics would not update, causing repeated VACUUM attempts.
  → **Test:** Scenario #24 verifies the `SET` is issued before VACUUM. Consider also testing that `conn.execute("SET statement_timeout = 0")` itself is resilient to errors.

- **[Edge Case] `asyncio.timeout` wrapping `while True` loop — if the loop body raises `asyncio.CancelledError` for a reason OTHER than the timeout, it will be caught by the same handler.**
  → The `except asyncio.TimeoutError` handler should be distinct from any `CancelledError` handling (in Python 3.9+, `TimeoutError` is a subclass of `CancelledError`). Using `except asyncio.TimeoutError` (not `except asyncio.CancelledError`) correctly scopes the catch.
  → **Test:** Scenario #1 should verify the specific exception type caught is `asyncio.TimeoutError`.

