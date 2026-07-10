# QA Strategy & Test Plan

## Coverage Map

<!-- 15 scenarios across 4 spec capabilities. Overlapping scenarios between
     per-stream-response-timeout and http2-stream-desync-fix are mapped to
     the same test function (both specs describe the same behavior from
     different perspectives). The MODIFIED requirement in http2-stream-desync-fix
     has no #### Scenario blocks; its behavioral aspects are covered by
     additional tests listed in the h2-connection-tests group. -->

| # | Spec Capability | Requirement | Scenario | Test File | Test Name | Group |
|---|---|---|---|---|---|---|
| 1 | per-stream-response-timeout | FixedHTTP2Connection enforces per-stream deadline from config | Deadline fires, semaphore released, connection survives | `tests/unit/core/http2/test_h2_connection.py` | `test_per_stream_timeout_fires_releases_semaphore_and_survives` | h2-connection-tests |
| 2 | per-stream-response-timeout | FixedHTTP2Connection enforces per-stream deadline from config | Deadline does not fire for normal response | `tests/unit/core/http2/test_h2_connection.py` | `test_per_stream_timeout_does_not_fire_for_fast_response` | h2-connection-tests |
| 3 | per-stream-response-timeout | FixedHTTP2Connection enforces per-stream deadline from config | stream_read from config takes priority over read | `tests/unit/core/http2/test_h2_connection.py` | `test_stream_read_takes_priority_over_read` | h2-connection-tests |
| 4 | per-stream-response-timeout | FixedHTTP2Connection enforces per-stream deadline from config | Default behavior when stream_read is not configured | `tests/unit/core/http2/test_h2_connection.py` | `test_stream_read_none_no_per_stream_timeout` | h2-connection-tests |
| 5 | http2-stream-desync-fix | Per-stream response header deadline | Per-stream timeout fires for starved stream | `tests/unit/core/http2/test_h2_connection.py` | `test_per_stream_timeout_fires_releases_semaphore_and_survives` | h2-connection-tests |
| 6 | http2-stream-desync-fix | Per-stream response header deadline | Per-stream timeout does not fire for fast response | `tests/unit/core/http2/test_h2_connection.py` | `test_per_stream_timeout_does_not_fire_for_fast_response` | h2-connection-tests |
| 7 | http2-stream-desync-fix | Per-stream response header deadline | stream_read overrides read | `tests/unit/core/http2/test_h2_connection.py` | `test_stream_read_takes_priority_over_read` | h2-connection-tests |
| 8 | http2-stream-desync-fix | Per-stream response header deadline | stream_read is None — no per-stream deadline | `tests/unit/core/http2/test_h2_connection.py` | `test_stream_read_none_no_per_stream_timeout` | h2-connection-tests |
| 9 | http2-stream-desync-fix | Per-stream response header deadline | RST_STREAM sent before semaphore release | `tests/unit/core/http2/test_h2_connection.py` | `test_rst_stream_sent_before_semaphore_release` | h2-connection-tests |
| 10 | http-client-pool-config | stream_read field in TimeoutConfig | stream_read accepts valid float | `tests/unit/config/test_timeout_config.py` | `test_stream_read_accepts_valid_float` | timeout-config-tests |
| 11 | http-client-pool-config | stream_read field in TimeoutConfig | stream_read defaults to None | `tests/unit/config/test_timeout_config.py` | `test_stream_read_defaults_to_none` | timeout-config-tests |
| 12 | http-client-pool-config | stream_read field in TimeoutConfig | stream_read rejects zero | `tests/unit/config/test_timeout_config.py` | `test_stream_read_rejects_zero` | timeout-config-tests |
| 13 | http-client-pool-config | stream_read field in TimeoutConfig | stream_read rejects negative | `tests/unit/config/test_timeout_config.py` | `test_stream_read_rejects_negative` | timeout-config-tests |
| 14 | request-lifecycle-timeout | Per-stream timeout is primary defense, total is backstop | Per-stream timeout fires before total deadline | `tests/stress/test_cascading_freeze.py` | `test_per_stream_timeout_fires_before_total_deadline` | stress-per-stream-tests |
| 15 | request-lifecycle-timeout | Per-stream timeout is primary defense, total is backstop | Total deadline fires when all retries time out | `tests/stress/test_cascading_freeze.py` | `test_total_deadline_fires_when_all_retries_time_out` | stress-per-stream-tests |

## Delegation Groups

<!-- Four non-overlapping groups. Each group owns exactly one test file.
      Groups are assigned to process-isolation groups G1, G2, G5, G6
      matching the project's Makefile test targets. -->

### Group: `h2-connection-tests`

**Scope:** `tests/unit/core/http2/test_h2_connection.py`

| Test File | Scenarios | Action |
|---|---|---|
| `tests/unit/core/http2/test_h2_connection.py` | 9 (scenarios #1–#9) + 2 additional tests for MODIFIED requirement behavioral aspects | MODIFY (6 new test functions in new `TestPerStreamTimeout` class + modify `_make_conn` helper) |

**Description:** Validates `FixedHTTP2Connection.handle_async_request()` per-stream timeout enforcement via `asyncio.wait_for()` wrapping `_receive_response()`. Covers all four spec capabilities' connection-level scenarios:

- **Timeout fires path (scenarios #1, #5):** `_receive_response` is mocked to hang beyond the deadline. Asserts `TimeoutError` is raised, `_h2_state.reset_stream(stream_id)` is called, `_write_outgoing_data(request)` is called, semaphore slot is released via `_response_closed`, `_events[stream_id]` is deleted, and a second stream on the same connection continues unaffected.
- **Fast response path (scenarios #2, #6):** `_receive_response` returns `(status, headers)` immediately. Asserts the `Response` object is returned with correct status/headers and no `TimeoutError`.
- **Priority resolution (scenarios #3, #7):** `request.extensions["stream_read"]` is set to a small value (e.g., `0.05`) while `request.extensions["timeout"]["read"]` is larger (e.g., `120.0`). Asserts `TimeoutError` fires after ~0.05s, proving `stream_read` takes priority.
- **No per-stream deadline (scenarios #4, #8):** `request.extensions["stream_read"]` is `None`, `request.extensions["timeout"]["read"]` is very small (e.g., `0.001`). Asserts `_receive_response` is called directly without `asyncio.wait_for` wrapping — the fast response returns normally, proving no per-stream timeout is applied when `stream_read` is `None`. The socket-level `read` timeout remains as the only backstop.
- **RST_STREAM ordering (scenario #9):** Asserts `reset_stream` + `_write_outgoing_data` are called in the inner `except TimeoutError` handler BEFORE the `TimeoutError` is re-raised to the outer `except BaseException` → `_response_closed` path. Uses `patch` to track call order.
- **MODIFIED requirement — send phases not wrapped:** `test_send_request_phases_not_wrapped_by_wait_for` verifies `_send_request_headers` and `_send_request_body` are NOT inside the `asyncio.wait_for` wrapper. Mocks `_send_request_headers` to sleep longer than the `stream_read` deadline; asserts no `TimeoutError` fires during the send phase.
- **MODIFIED requirement — TimeoutError flows through _response_closed:** `test_timeout_error_handled_by_response_closed` verifies that `TimeoutError` from `asyncio.wait_for` enters the `except BaseException` block, triggering `_response_closed` with `AsyncShieldCancellation`. Asserts semaphore is released and `_events` cleaned up, proving the existing cleanup path handles per-stream `TimeoutError` identically to any other exception.

All tests use the existing `_make_conn()` helper (modified to accept `request.extensions` setup) with `unittest.mock.AsyncMock` / `MagicMock` / `patch`. No `pytest-mock` / `mocker` fixture. All timeout values use small deltas (0.01–0.1s) for fast unit-test execution. Config values derive from `CanonicalConfig.from_example_files()` for `timeout_read` and `timeout_total` references.

---

### Group: `timeout-config-tests`

**Scope:** `tests/unit/config/test_timeout_config.py`

| Test File | Scenarios | Action |
|---|---|---|
| `tests/unit/config/test_timeout_config.py` | 4 (scenarios #10–#13) + 1 modification to existing default values test | MODIFY (4 new test functions in new `TestStreamReadField` class + modify `TestTimeoutConfigDefaults.test_ut_tc01_all_default_values`) |

**Description:** Validates the new `stream_read: float | None = None` field in `TimeoutConfig` (Pydantic v2 schema). Covers all four `http-client-pool-config` scenarios:

- **Valid float (scenario #10):** `TimeoutConfig(stream_read=30.0)` → `stream_read == 30.0`. Also tests via YAML loading through `ConfigLoader` with `timeouts: { stream_read: 30.0 }`.
- **Default None (scenario #11):** `TimeoutConfig()` without `stream_read` → `stream_read is None`. Also tests via YAML loading when `stream_read` is omitted from the `timeouts` block.
- **Rejects zero (scenario #12):** `TimeoutConfig(stream_read=0.0)` raises `ValidationError` with "greater than 0" message. Validates the `gt=0` constraint.
- **Rejects negative (scenario #13):** `TimeoutConfig(stream_read=-5.0)` raises `ValidationError` with "greater than 0" message.
- **Modification to `test_ut_tc01_all_default_values`:** Add `assert timeouts.stream_read is None` to the existing default-values test, ensuring the new field's default is verified alongside existing fields.

All config values derive from `CanonicalConfig.from_example_files()` for default-value assertions. YAML loading tests use `mock_open` with inline YAML (consistent with existing test patterns in the file). No hardcoded provider tokens or API URLs.

---

### Group: `stress-per-stream-tests`

**Scope:** `tests/stress/test_cascading_freeze.py`

| Test File | Scenarios | Action |
|---|---|---|
| `tests/stress/test_cascading_freeze.py` | 2 (scenarios #14–#15) | MODIFY (2 new test functions + modify `_make_client` helper to accept `stream_read` parameter) |

**Description:** Validates the request-lifecycle timeout interaction using a real HTTP/2 server (`EphemeralHttp2Server`) with drip-feed body chunks. These stress tests prove the per-stream timeout actually fires under real HTTP/2 multiplexing — the core fix that the existing `test_read_timeout_silence_with_drip_feed` test proves is broken without the fix.

- **Per-stream fires before total (scenario #14):** Server advertises 100 streams but processes only 2 concurrently with 5s delay and 500ms drip-feed chunks (same setup as `test_read_timeout_silence_with_drip_feed`). Client is configured with `stream_read=3.0` (shorter than the 5s delay) and `total=30.0`. Asserts: starved streams receive `TimeoutError` at ~3s (not 5s+), `NETWORK_ERROR` is returned to the caller, and the total deadline (30s) does NOT fire. This is the direct counterpart to the existing `test_read_timeout_silence_with_drip_feed` which proves the socket-level timeout does NOT fire — the new test proves the per-stream timeout DOES fire.
- **Total deadline fires when all retries time out (scenario #15):** Server configured to never send response headers for starved streams (no drip-feed, pure starvation). Client configured with `stream_read=2.0` and `total=7.0` (allowing ~3 per-stream timeouts within the total window). Asserts: multiple per-stream timeouts occur (~2s each), and if the retry loop does not exhaust retries, the `asyncio.timeout(total)` fires and returns a 504/gateway error. If retries ARE exhausted, the gateway returns an error before the total deadline.

Both tests use `@pytest.mark.slow` and `@pytest.mark.asyncio` decorators. The `_make_client` helper is modified to accept an optional `stream_read: float | None = None` parameter that injects `request.extensions["stream_read"]` via a custom transport wrapper or httpx event hook. All timeout values are test-local (not from `CanonicalConfig`) because stress tests require precise timing control — annotated with `# boundary: stress-test-timing` if needed for the gatekeeper. Run via `make test-slow` (G6).

---

### Group: `canonical-config-tests`

**Scope:** `tests/_canonical.py`, `tests/test_canonical_config.py`

| Test File | Scenarios | Action |
|---|---|---|
| `tests/_canonical.py` | 0 (infrastructure — no spec scenarios) | MODIFY (add `timeout_stream_read` field to `CanonicalConfig` dataclass + parsing logic) |
| `tests/test_canonical_config.py` | 0 (infrastructure) | MODIFY (add assertion for `timeout_stream_read` in `test_parses_example_files_correctly`) |

**Description:** Updates `CanonicalConfig` to expose the new `stream_read` field from the example config YAML. This ensures all downstream tests that reference `CanonicalConfig.from_example_files()` can access `cfg.timeout_stream_read` for zero-hardcode compliance.

- **`tests/_canonical.py` modifications:**
  - Add `timeout_stream_read: float | None` field to the `CanonicalConfig` frozen dataclass (in the `=== Timeouts ===` section, after `timeout_total`).
  - Add parsing logic in `from_example_files()`: `timeout_stream_read=timeouts.get("stream_read", None)` — reads from the first provider's `timeouts` block in `example_full_config.yaml`. Since `deepseek-main` will get an explicit `timeouts` block (config audit fix), and `llm_provider_default` in `defaults.py` will get `stream_read: None`, the canonical value will be `None` unless a provider explicitly sets it.
  - Update the docstring `Fields:` section to document `timeout_stream_read`.
- **`tests/test_canonical_config.py` modifications:**
  - Add `assert cfg.timeout_stream_read is None` (or the value from the example config) to `test_parses_example_files_correctly` in the `=== Timeouts ===` assertion block, after `assert cfg.timeout_total == 600.0`.

No new test functions needed — the existing `test_parses_example_files_correctly` and `test_import_safe_from_any_test_file` cover the new field by extension once it is added to the dataclass. Run via `make test` (G5 — root-level gatekeeper tests).

---

## Test Modifications

<!-- Existing tests that need updating due to this change. Each modification
      references the spec scenario or design decision that motivates it. -->

### File: `tests/unit/core/http2/test_h2_connection.py`

| Change | Reason |
|---|---|
| **MODIFY** `_make_conn()` helper: Add optional `stream_read: float \| None = None` and `read_timeout: float = 120.0` parameters. These are not set on the connection itself but are used by new tests to construct mock requests with the correct `request.extensions` dict. Also add `conn._read_lock = asyncio.Lock()` to the helper (currently set ad-hoc in `_receive_events` tests only) since `handle_async_request` may call `_receive_events` indirectly. | New tests for `handle_async_request` need mock requests with `request.extensions["stream_read"]` and `request.extensions["timeout"]["read"]`. The helper currently does not support constructing such requests. Design Decision 2 (pass through `request.extensions`). |
| **NEW** `TestPerStreamTimeout` class: 6 new test functions (`test_per_stream_timeout_fires_releases_semaphore_and_survives`, `test_per_stream_timeout_does_not_fire_for_fast_response`, `test_stream_read_takes_priority_over_read`, `test_stream_read_none_falls_back_to_read`, `test_rst_stream_sent_before_semaphore_release`, `test_send_request_phases_not_wrapped_by_wait_for`). Each test constructs a mock `request` with `request.extensions` dict, mocks `_send_request_headers`/`_send_request_body`/`_receive_response`/`_write_outgoing_data` as `AsyncMock`, and calls `await conn.handle_async_request(request)`. | Scenarios #1–#9 (per-stream-response-timeout + http2-stream-desync-fix). MODIFIED requirement behavioral aspects (send phases outside wrapper, TimeoutError through _response_closed). Design Decisions 3, 4. |
| **MODIFY** `test_response_closed_cancelled_stream_reset`: Add a comment documenting that this test also covers the MODIFIED requirement's claim that `except BaseException` → `_response_closed` handles `TimeoutError` identically to `CancelledError` — both are `BaseException` subclasses that bypass `except Exception`. The existing assertions (`reset_stream` called, semaphore released, `_events` deleted) already verify the cleanup path. | MODIFIED requirement: "The existing `except BaseException` → `_response_closed` cleanup path SHALL handle `TimeoutError` from the per-stream deadline identically to any other exception." |

### File: `tests/unit/config/test_timeout_config.py`

| Change | Reason |
|---|---|
| **MODIFY** `test_ut_tc01_all_default_values`: Add `assert timeouts.stream_read is None` after the existing `assert timeouts.total == 600.0`. | Scenario #11 (stream_read defaults to None). The existing default-values test must verify the new field's default alongside existing fields. |
| **MODIFY** `test_ut_tc03_partial_override_preserves_unset_defaults`: Add `assert timeouts.stream_read is None` to verify that partially overriding other fields preserves `stream_read`'s default. | Scenario #11. Partial override must not affect `stream_read` default. |
| **MODIFY** `test_ut_tc05_all_fields_custom_values`: Add `stream_read=300.0` to the constructor call and `assert timeouts.stream_read == 300.0` to assertions. | Scenario #10. The "all fields custom" test should include the new field. |
| **NEW** `TestStreamReadField` class: 4 new test functions (`test_stream_read_accepts_valid_float`, `test_stream_read_defaults_to_none`, `test_stream_read_rejects_zero`, `test_stream_read_rejects_negative`). Tests direct construction and YAML loading. | Scenarios #10–#13 (http-client-pool-config). |
| **MODIFY** `test_ut_tc15_yaml_with_all_timeout_fields`: Add `stream_read: 300.0` to the YAML `timeouts` block and `assert provider.timeouts.stream_read == 300.0` to assertions. | Scenario #10. The "all timeout fields from YAML" test should include the new field. |

### File: `tests/_canonical.py`

| Change | Reason |
|---|---|
| **MODIFY** `CanonicalConfig` dataclass: Add `timeout_stream_read: float | None` field in the `=== Timeouts ===` section, after `timeout_total: float`. | Infrastructure: CanonicalConfig must expose the new `stream_read` field for zero-hardcode compliance in downstream tests. Design Decision 1 (new `stream_read` field). |
| **MODIFY** `from_example_files()` classmethod: Add `timeout_stream_read=timeouts.get("stream_read")` to the constructor call. The `timeouts` dict is already extracted from the first provider with a `timeouts` block. If no provider sets `stream_read`, the value is `None` (Python dict `.get()` default). | Infrastructure: parse the new field from `example_full_config.yaml`. |
| **MODIFY** docstring `Fields:` section: Add `timeout_stream_read: Per-stream response header timeout in seconds (None = no per-stream deadline, socket-level read timeout remains).` | Documentation: keep the docstring in sync with the dataclass fields. |

### File: `tests/test_canonical_config.py`

| Change | Reason |
|---|---|
| **MODIFY** `test_parses_example_files_correctly`: Add `assert cfg.timeout_stream_read is None` (or the value from the example config if a provider sets it) in the `=== Timeouts ===` assertion block, after `assert cfg.timeout_total == 600.0`. | Infrastructure: verify CanonicalConfig correctly parses the new field. |

### File: `tests/unit/providers/test_base.py`

| Change | Reason |
|---|---|
| **NEW** `test_send_proxy_request_injects_stream_read_into_extensions`: Create a provider with `config.timeouts.stream_read = 30.0`. Mock `client.send` to capture the `request` object. Call `await provider._send_proxy_request(mock_client, mock_request)`. Assert `mock_request.extensions["stream_read"] == 30.0` was set before `client.send` was called. Use `mock_client.send.call_args` to inspect the request passed to `send()`. | Design Decision 2: "Inject `stream_read` into `request.extensions` in `_send_proxy_request` (one line before `client.send()`)." No spec scenario covers the injection point directly, but it is the critical wiring between config and connection. |
| **NEW** `test_send_proxy_request_injects_stream_read_none_when_unset`: Create a provider with `config.timeouts.stream_read = None` (default). Mock `client.send`. Assert `mock_request.extensions["stream_read"] is None` — the injection still happens (key exists) but value is `None`, meaning no per-stream deadline (socket-level `read` remains). | Design Decision 5: "Default `stream_read=None` means no per-stream deadline." The injection must set the key to `None` (not omit it). |
| **MODIFY** existing `_send_proxy_request` tests that assert `mock_client.send.assert_called_once()`: Add assertion that `request.extensions` contains `"stream_read"` key. This is a lightweight addition to existing tests (e.g., `test_send_proxy_request_success_returns_body_none`, `test_send_proxy_request_never_calls_aclose`) to verify the injection is always performed. | Design Decision 2. Ensures the injection is not accidentally removed in future refactors. |

### File: `tests/unit/config/test_defaults.py`

| Change | Reason |
|---|---|
| **MODIFY** `test_default_config_keys_and_values` (or add new test): Assert that `defaults["providers"]["llm_provider_default"]["timeouts"]["stream_read"]` exists and is `None`. This verifies that `defaults.py` includes the new `stream_read: None` field in the default `timeouts` block. | Config audit: "defaults.py gets `stream_read: null`". The defaults template must include the new field so generated configs are complete. |

### File: `config/example_full_config.yaml` (config audit — covered by existing tests)

| Change | Reason |
|---|---|
| **MODIFY** `deepseek-main` provider: Add explicit `timeouts` block (with `connect`, `read`, `write`, `pool`, `total`, `stream_read: null`) and `gateway_policy` block (with `streaming_mode`, `debug_mode`, `retry`). Currently `deepseek-main` omits both blocks with a comment "Using default health and gateway policies by omitting them". | Config audit: "example_full_config.yaml: deepseek-main gets explicit `timeouts` and `gateway_policy` blocks". This fixes config staleness — the example should be complete and self-documenting. Covered by existing CanonicalConfig integrity tests (G5) and `test_full_config_key_order` in `test_defaults.py`. |

### File: `src/config/defaults.py` (config audit — covered by existing tests)

| Change | Reason |
|---|---|
| **MODIFY** `get_default_config()`: Add `"stream_read": None` to the `timeouts` dict in `llm_provider_default` provider. The `pool_health_log_interval_sec` field is already present in `HttpClientConfig` (line 492 of `schemas.py`) and tested in `test_http_client_config.py` (UT-HC25–UT-HC28) — no change needed there. | Config audit: "defaults.py gets `stream_read: null` and `pool_health_log_interval_sec: 60`". The latter is already done; only `stream_read: None` needs adding to the defaults template. Covered by `test_defaults.py` (G2). |

---

## Risks & Edge Cases

<!-- Scenarios from design.md Risks / Trade-offs section that need dedicated
      test coverage. Each risk maps to a concrete test or existing test. -->

### Risk: Per-stream timeout fires during legitimate model "thinking"

- **Source:** design.md Risks / Trade-offs, bullet 1.
- **Mitigation in code:** The timeout only wraps `_receive_response` (the headers-wait phase), not body streaming. If the server sends `200 OK` immediately (OpenAI-compatible pattern), the timer stops and thinking happens during body streaming — no timeout. If the server delays headers, `stream_read` can be set high (300s for DashScope) or left at `read` default (120s). Design Decision 3.
- **Dedicated test:** `test_per_stream_timeout_does_not_fire_for_fast_response` (Coverage Map #2, #6) — mocks `_receive_response` to return headers immediately, verifies no `TimeoutError` and the `Response` is returned normally. This proves the timer stops once headers arrive, allowing unlimited time for body streaming (thinking).
- **Additional coverage:** The stress test `test_per_stream_timeout_fires_before_total_deadline` (Coverage Map #14) uses `stream_headers=True` on the ephemeral server — active streams that send headers immediately do NOT time out, only starved streams (no headers) do.

### Risk: `stream_read` injection in `_send_proxy_request` might interfere with httpx internals

- **Source:** design.md Risks / Trade-offs, bullet 2.
- **Mitigation in code:** `request.extensions` is explicitly designed as an extension point. httpx preserves unknown keys. The key `"stream_read"` does not collide with any httpx internal key. Design Decision 2.
- **Dedicated test:** `test_send_proxy_request_injects_stream_read_into_extensions` (Test Modifications — `test_base.py`) — verifies the injection sets `request.extensions["stream_read"]` to the configured value before `client.send()`. The test also implicitly verifies no httpx error is raised from the unknown extension key (the mock `client.send` accepts the request without complaint).
- **Additional coverage:** All existing `_send_proxy_request` tests in `test_base.py` continue to pass after the injection line is added, proving backward compatibility — the one-line addition does not break any existing request-sending behavior.

### Risk: Timeout during `_write_outgoing_data` after `reset_stream` could leave stream in inconsistent state

- **Source:** design.md Risks / Trade-offs, bullet 3.
- **Mitigation in code:** The `try/except` in `_response_closed` (lines 103–109 of `h2_connection.py`) already handles `NoSuchStreamError` and `ProtocolError` from `reset_stream`. Even if `_write_outgoing_data` fails, the outer `except BaseException` + `AsyncShieldCancellation` ensures `_response_closed` runs and the semaphore is released. Design Decision 4.
- **Dedicated test:** `test_rst_stream_sent_before_semaphore_release` (Coverage Map #9) — verifies `reset_stream` and `_write_outgoing_data` are called in the inner `except TimeoutError` handler before re-raising. The test also verifies that even if `_write_outgoing_data` is mocked to raise, the outer `except BaseException` → `_response_closed` still runs and releases the semaphore.
- **Additional coverage:** `test_response_closed_cancelled_stream_reset` (existing test, MODIFIED) — verifies `_response_closed` handles `reset_stream` on a non-clean stream, which is the exact code path that the inner `except TimeoutError` handler relies on.

### Trade-off: Socket-level `read` timeout still exists as backstop

- **Source:** design.md Risks / Trade-offs, trade-off bullet.
- **Mitigation in code:** The socket-level `read` timeout can fire independently (killing the entire connection) if the socket is silent for `read` seconds. This is acceptable as a backstop; the per-stream timeout fires first in the common case (active socket, starved stream).
- **Dedicated test:** The existing `test_read_timeout_silence_with_drip_feed` (in `test_cascading_freeze.py`) PROVES the socket-level timeout does NOT fire for starved streams when active streams keep the socket busy. The new `test_per_stream_timeout_fires_before_total_deadline` (Coverage Map #14) uses the SAME server setup but WITH the per-stream timeout fix, proving the per-stream timeout DOES fire where the socket-level timeout did not. Together, these two tests form a before/after proof of the fix.
- **Additional coverage:** `test_total_deadline_fires_when_all_retries_time_out` (Coverage Map #15) — verifies the `asyncio.timeout(total)` backstop fires when per-stream timeouts exhaust all retries, proving the total deadline still works as the final safety net.

### Edge Case: `stream_read` is `None` — no per-stream deadline

- **Source:** Design Decision 5: "Default `stream_read=None` means no per-stream deadline (socket-level `read` remains as backstop)."
- **Mitigation in code:** In `handle_async_request`, when `stream_read` is `None`, `_receive_response` is called directly without `asyncio.wait_for` wrapping. The socket-level `read` timeout remains as the only backstop — preserving the original behavior where active streams keep the socket busy and a starved stream does NOT time out.
- **Dedicated tests:**
  - `test_stream_read_none_no_per_stream_timeout` (Coverage Map #4, #8) — sets `request.extensions["stream_read"] = None` with a very small `read_timeout=0.001`, verifies the response returns normally (no per-stream timeout fires).
  - `test_send_proxy_request_injects_stream_read_none_when_unset` (Test Modifications — `test_base.py`) — verifies the injection sets the key to `None` (not omits it) when `stream_read` is unconfigured.

### Edge Case: Multiple streams on the same connection — one times out, others survive

- **Source:** Scenarios #1, #5: "other streams on the same connection SHALL continue unaffected."
- **Mitigation in code:** The per-stream timeout fires `asyncio.wait_for` on a single `_receive_response` call for a specific `stream_id`. The `RST_STREAM` frame is sent for that stream only. Other streams' `_events` entries and semaphore slots are untouched.
- **Dedicated test:** `test_per_stream_timeout_fires_releases_semaphore_and_survives` (Coverage Map #1, #5) — sets up two streams on the same connection, makes one `_receive_response` hang, verifies the other stream's `_events` entry is still present and the connection state is not `CLOSED`.

---

## Testing Paradigm

- **Framework:** pytest ≥9.0 + pytest-asyncio (strict mode). All async tests use `@pytest.mark.asyncio` decorator with `async def`. No auto-detection.
- **Mocking:** `unittest.mock` only (`AsyncMock`, `MagicMock`, `patch`). **Do NOT use `pytest-mock` / `mocker` fixture** — it is intentionally absent from the project.
- **Zero hardcodes:** All configuration values must derive from `CanonicalConfig` at `tests/_canonical.py`. Use `CanonicalConfig.from_example_files()` for all config values. No hardcoded DB credentials, provider tokens, or API URLs. Stress tests use test-local timing values (e.g., `stream_read=3.0`, `total=30.0`) for precise control — annotate with `# boundary: stress-test-timing` if the gatekeeper flags them.
- **Test directories:**
  - `tests/unit/core/http2/` — G1 unit tests (run via `make test` or `poetry run pytest tests/unit/core/http2/ -q --timeout=30`)
  - `tests/unit/config/` — G2 config tests (run via `make test` or `poetry run pytest tests/unit/config/ -q --timeout=30`)
  - `tests/stress/` — G6 stress tests (run via `make test-slow` or `poetry run pytest tests/stress/ -q --timeout=60`)
  - `tests/` (root) — G5 gatekeeper tests (run via `make test`)
- **Test naming:** test files = `test_<snake_case>.py`, test classes = `class Test<Thing>:`, test functions = `test_<snake_case>`.
- **Markers:**
  - `@pytest.mark.asyncio` — all async tests
  - `@pytest.mark.slow` — stress tests only (G6)
  - `@pytest.mark.timeout(N)` — per-test timeout (stress tests use 30–60s)
- **Group reference:**
  - G1 = unit tests in `tests/unit/` excluding `tests/unit/config/`
  - G2 = config tests in `tests/unit/config/`
  - G5 = root-level gatekeeper tests in `tests/test_*.py`
  - G6 = stress tests in `tests/stress/` (`@pytest.mark.slow`, via `make test-slow`)
- **Gatekeeper:** Run `bash scripts/check-test-hardcodes.sh all` — must exit 0 before commit. For boundary tests needing banned values, annotate with `# boundary: <reason>`.
- **Coverage:** No fail-under threshold. pytest-cov for informational coverage only.
- **Existing fixtures:** `tests/conftest.py` provides autouse `_set_config_vars_from_canonical` that monkeypatches all 17 env vars before every test. Tests do not need to set env vars manually.
- **Existing helpers:** `test_h2_connection.py` provides `_make_conn()` — reuse and extend for new per-stream timeout tests. `test_cascading_freeze.py` provides `_make_client()` and `_timed_get()` — reuse and extend for new stress tests. `test_timeout_config.py` provides YAML loading patterns via `mock_open` — reuse for `stream_read` YAML tests.
- **Quality gates:** All changes must pass: `poetry run pyright` (strict on `src/core/`, `src/config/`), `poetry run ruff check src/ tests/`, `poetry run black --check src/ tests/`, `make test`, `bash scripts/check-test-hardcodes.sh all`.
