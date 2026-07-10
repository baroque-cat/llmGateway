# QA Strategy & Test Plan

## Coverage Map

| # | Spec Capability | Requirement | Scenario | Test File | Test Name | Group |
|---|---|---|---|---|---|---|
| 1 | stream-monitor-graceful-shutdown | StreamMonitor finalizes on all exit paths | CancelledError triggers aclose | `tests/unit/services/test_gateway_service_stream_monitor.py` | `test_cancelled_error_triggers_finalize_and_aclose` | stream-monitor-tests |
| 2 | stream-monitor-graceful-shutdown | StreamMonitor finalizes on all exit paths | GeneratorExit triggers aclose | `tests/unit/services/test_gateway_service_stream_monitor.py` | `test_generator_exit_triggers_finalize_and_aclose` | stream-monitor-tests |
| 3 | stream-monitor-graceful-shutdown | StreamMonitor finalizes on all exit paths | Normal stream completion triggers aclose | `tests/unit/services/test_gateway_service_stream_monitor.py` | `test_stream_monitor_success` | stream-monitor-tests |
| 4 | stream-monitor-graceful-shutdown | StreamMonitor finalizes on all exit paths | ReadError triggers aclose then re-raises GatewayStreamError | `tests/unit/services/test_gateway_service_stream_monitor.py` | `test_stream_monitor_read_error_raises_gateway_stream_error` | stream-monitor-tests |
| 5 | stream-monitor-graceful-shutdown | Idempotent finalization | Double finalize is safe | `tests/unit/services/test_gateway_service_stream_monitor.py` | `test_double_finalize_is_safe_noop` | stream-monitor-tests |
| 6 | stream-monitor-graceful-shutdown | aclose failures are logged, not raised | aclose raises in finally | `tests/unit/services/test_gateway_service_stream_monitor.py` | `test_aclose_failure_in_finally_logged_not_raised` | stream-monitor-tests |
| 7 | request-lifecycle-timeout | Timeout handler closes upstream response | Timeout fires with open upstream response | `tests/unit/services/test_gateway_timeout.py` | `test_timeout_calls_discard_response_with_open_stream` | timeout-handler-tests |
| 8 | request-lifecycle-timeout | Timeout handler closes upstream response | Timeout fires after response already closed | `tests/unit/services/test_gateway_timeout.py` | `test_timeout_after_discard_is_safe_noop` | timeout-handler-tests |
| 9 | request-lifecycle-timeout | Timeout handler closes upstream response | Timeout fires before any proxy_request call | `tests/unit/services/test_gateway_timeout.py` | `test_timeout_before_proxy_request_skips_discard` | timeout-handler-tests |
| 10 | request-lifecycle-timeout | Timeout handler closes upstream response | discard_response failure is logged, not raised | `tests/unit/services/test_gateway_timeout.py` | `test_discard_response_failure_logged_not_raised` | timeout-handler-tests |

## Delegation Groups

### Group: `stream-monitor-tests`

**Scope:** `tests/unit/services/test_gateway_service_stream_monitor.py`

| Test File | Scenarios | Action |
|---|---|---|
| `tests/unit/services/test_gateway_service_stream_monitor.py` | 6 | MODIFY (4 new test functions + 3 modified existing test functions) |

**Description:** Validates `StreamMonitor.__anext__` graceful shutdown on every exit path (`CancelledError`, `GeneratorExit`, `StopAsyncIteration`, `httpx.ReadError`, unexpected exceptions) via a `finally` block. Verifies idempotency of `_finalize_logging()` via the `_finalized` guard flag and confirms `aclose()` failures are logged-not-raised. New tests are added to a new `TestStreamMonitorGracefulShutdown` class; three existing tests in `TestStreamMonitor` are modified — two to assert the exactly-once guarantee under the new `finally` code path, and one (`test_stream_monitor_exception_during_stream`) to remove stale assertions for the deleted `except Exception` block (Design Decision 3).

---

### Group: `timeout-handler-tests`

**Scope:** `tests/unit/services/test_gateway_timeout.py`

| Test File | Scenarios | Action |
|---|---|---|
| `tests/unit/services/test_gateway_timeout.py` | 4 | MODIFY (4 new test functions added to existing file) |

**Description:** Validates the `finally` block in `_handle_buffered_retryable_request` that calls `discard_response(upstream_response, body_bytes)` on `asyncio.TimeoutError`. Covers all four states: open stream (`body_bytes is None` → `aclose` invoked), already-closed stream (`body_bytes is not None` → safe no-op), no upstream response yet (`upstream_response is None` → skip entirely), and `discard_response` raising an exception (logged, original `TimeoutError` not masked). New tests are added to a new `TestTimeoutDiscardResponse` class.

---

## Test Modifications

### File: `tests/unit/services/test_gateway_service_stream_monitor.py`

| Change | Reason |
|---|---|
| **MODIFY** `test_stream_monitor_exception_during_stream`: Remove assertions `mock_logger.error.assert_called_once()` and `"Error during streaming" in mock_logger.error.call_args[0][0]`. Retain `pytest.raises(RuntimeError, match="Stream broken")`. Add assertion that `mock_logger.info.assert_called_once()` (finalize logging via `finally`) and `mock_httpx_response.aclose.assert_called_once()` still hold. | Design Decision 3 removes the `except Exception` block from `__anext__`. The `logger.error("Error during streaming")` call no longer exists, so the old assertions will fail. The `finally` block now guarantees `_finalize_logging()` + `aclose()` on unexpected exceptions. References: Scenario "StreamMonitor finalizes on all exit paths" (unexpected exceptions path), Design Decision 3. |
| **MODIFY** `test_stream_monitor_success`: Add explicit assertion comment documenting that `mock_httpx_response.aclose.assert_called_once()` and `mock_logger.info.assert_called_once()` verify the exactly-once guarantee under the new `finally` block (where both `except StopAsyncIteration` and `finally` reach `_finalize_logging()`). | After adding the `finally` block, normal completion (`StopAsyncIteration`) triggers two code paths to `_finalize_logging()`. The `_finalized` guard flag (Design Decision 2) must prevent double invocation. The existing `assert_called_once()` assertions already verify this but should be annotated to make the intent explicit. References: Scenario "Normal stream completion triggers aclose", Design Decision 2. |
| **MODIFY** `test_stream_monitor_read_error_raises_gateway_stream_error`: Add explicit assertion comment documenting that `mock_httpx_response.aclose.assert_called_once()` verifies idempotency under the new `finally` block (where both `except httpx.ReadError` and `finally` reach `_finalize_logging()`). | After adding the `finally` block, `ReadError` triggers two code paths to `_finalize_logging()`. The `_finalized` flag must prevent double invocation. The existing `assert_called_once()` assertions verify this but should be annotated to make the intent explicit. References: Scenario "ReadError triggers aclose then re-raises GatewayStreamError", Design Decision 2. |
| **NEW** `test_cancelled_error_triggers_finalize_and_aclose`: Create a `StreamMonitor` with a mock upstream response whose `aiter_bytes()` iterator blocks on an `asyncio.Event`. Start iterating via `async for`, then cancel the task. Assert `_finalize_logging()` was called (info log), `aclose()` was called, and `CancelledError` propagated to the caller. | Scenario "CancelledError triggers aclose". `CancelledError` is a `BaseException` subclass that bypasses the current `except Exception` block. The `finally` block must catch it. References: Design Decision 1. |
| **NEW** `test_generator_exit_triggers_finalize_and_aclose`: Create a `StreamMonitor`, start iterating, then call `aclose()` on the async generator. Assert `_finalize_logging()` was called (info log) and `aclose()` was called. | Scenario "GeneratorExit triggers aclose". `GeneratorExit` is not caught by any `except` clause — only `finally` guarantees cleanup. References: Design Decision 1. |
| **NEW** `test_double_finalize_is_safe_noop`: Call `_finalize_logging()` manually on a `StreamMonitor` instance, then call it again. Assert the second call is a no-op (no second info log, no second `aclose()`). | Scenario "Double finalize is safe". The `_finalized` guard flag must prevent double invocation. References: Design Decision 2. |
| **NEW** `test_aclose_failure_in_finally_logged_not_raised`: Configure `upstream_response.aclose` to raise `RuntimeError("aclose failed")`. Trigger finalization (e.g., via normal stream completion). Assert `logger.error` was called with `exc_info=True`, the original exception (if any) propagated correctly, and no new exception was raised from `_finalize_logging()`. | Scenario "aclose raises in finally". `aclose()` failures must be caught and logged, not propagated, to avoid masking the original exception. References: Design Decision 5. |

### File: `tests/unit/services/test_gateway_timeout.py`

| Change | Reason |
|---|---|
| **NEW** `test_timeout_calls_discard_response_with_open_stream`: Configure `provider.proxy_request` to return a response with `body_bytes=None` (stream still open). Use a short timeout that fires during `proxy_request`. Assert `discard_response` was called with the upstream response and `body_bytes=None`, and that `upstream_response.aclose()` was invoked. Assert 504 JSONResponse returned. | Scenario "Timeout fires with open upstream response". The `finally` block must call `discard_response()` which calls `aclose()` when `body_bytes is None`. Existing tests patch `discard_response` as a no-op `AsyncMock` and use `body_bytes=b""`, so they do not cover this scenario. References: Design Decision 4. |
| **NEW** `test_timeout_after_discard_is_safe_noop`: Configure `provider.proxy_request` to return a response with `body_bytes=b""` (already read). Use a short timeout that fires during backoff sleep (after `discard_response` was already called in the retry loop). Assert `discard_response` is called in `finally` but `upstream_response.aclose()` is NOT called (since `body_bytes is not None`). Assert 504 JSONResponse returned. | Scenario "Timeout fires after response already closed". When `body_bytes is not None`, `discard_response` is a safe no-op. References: Design Decision 4, `discard_response` implementation in `response_forwarder.py`. |
| **NEW** `test_timeout_before_proxy_request_skips_discard`: Use an `_ImmediateTimeout` context manager that raises `TimeoutError` on `__aenter__`, before any `proxy_request` call. Assert `discard_response` is NOT called (since `upstream_response is None`). Assert 504 JSONResponse returned with `attempts=0` and `last_error="unknown"`. | Scenario "Timeout fires before any proxy_request call". The `finally` block must skip `discard_response()` entirely when `upstream_response is None`. References: Design Decision 4. |
| **NEW** `test_discard_response_failure_logged_not_raised`: Configure `discard_response` to raise `RuntimeError("discard failed")`. Trigger a timeout. Assert `logger.error` was called with `exc_info=True`, the original `TimeoutError` was not masked, and the 504 JSONResponse was still returned. | Scenario "discard_response failure is logged, not raised". Cleanup failures in `finally` must be caught and logged, not propagated. References: Design Decision 5. |
| **MODIFY** `test_timeout_returns_504_when_loop_exceeds_deadline`: Save a reference to the `discard_response` `AsyncMock` (instead of inline `new=AsyncMock()`). After the fix, add assertion `mock_discard.assert_called()` to verify the `finally` block invokes `discard_response`. | After Design Decision 4, the `finally` block calls `discard_response`. The existing test patches it as an inline no-op `AsyncMock` without saving a reference, so it cannot verify the call. Modifying to save the reference and assert it was called ensures the `finally` block is wired correctly. References: Scenario "Timeout fires with open upstream response", Design Decision 4. |

---

## Risks & Edge Cases

### Risk: `_finalize_logging()` in `finally` masks original exception if `aclose()` raises

- **Source:** design.md Risks / Trade-offs, bullet 1.
- **Mitigation in code:** `aclose()` is wrapped in `try/except` with `logger.error(exc_info=True)` (Design Decision 5).
- **Dedicated test:** `test_aclose_failure_in_finally_logged_not_raised` (Coverage Map #6) — configures `aclose` to raise, verifies the error is logged with `exc_info=True`, the original exception propagates, and no new exception escapes `_finalize_logging()`.

### Risk: `discard_response()` in `finally` closes a stream still used by `StreamingResponse`

- **Source:** design.md Risks / Trade-offs, bullet 2.
- **Mitigation in code:** `discard_response` only calls `aclose()` when `body_bytes is None`. For success paths where `StreamingResponse` is returned, `body_bytes` is `None`, but `aclose()` on an already-closed response is a safe no-op in httpx.
- **Dedicated tests:**
  - `test_timeout_calls_discard_response_with_open_stream` (Coverage Map #7) — verifies `aclose()` IS called when `body_bytes is None` (the leak-prevention path).
  - `test_timeout_after_discard_is_safe_noop` (Coverage Map #8) — verifies `aclose()` is NOT called when `body_bytes is not None` (the safe no-op path), confirming `discard_response` does not interfere with already-closed responses.

### Risk: Double-`aclose()` from `StopAsyncIteration` + `finally`

- **Source:** design.md Risks / Trade-offs, bullet 3.
- **Mitigation in code:** `_finalized` boolean flag ensures exactly-one invocation of `_finalize_logging()` (Design Decision 2).
- **Dedicated tests:**
  - `test_double_finalize_is_safe_noop` (Coverage Map #5) — calls `_finalize_logging()` twice directly, asserts the second call is a no-op.
  - `test_stream_monitor_success` (Coverage Map #3, MODIFIED) — verifies `aclose.assert_called_once()` and `info.assert_called_once()` still hold under the new `finally` code path where `StopAsyncIteration` triggers both `except` and `finally`.
  - `test_stream_monitor_read_error_raises_gateway_stream_error` (Coverage Map #4, MODIFIED) — verifies `aclose.assert_called_once()` holds under the new `finally` code path where `httpx.ReadError` triggers both `except` and `finally`.

### Trade-off: Removing `except Exception` + `logger.error(...)` silences some unexpected streaming exceptions

- **Source:** design.md Risks / Trade-offs, trade-off bullet.
- **Mitigation in code:** The exception propagates to FastAPI's exception handler which logs it. The key invariant (`aclose()` is called) is preserved by the `finally` block.
- **Dedicated test:** `test_stream_monitor_exception_during_stream` (MODIFIED) — verifies that a `RuntimeError` during streaming propagates to the caller, `_finalize_logging()` is still called (via `finally`), and `aclose()` is invoked. The old assertions for `logger.error("Error during streaming")` are removed since that code path no longer exists.

### Edge Case: `GeneratorExit` vs `CancelledError` distinction

- `GeneratorExit` is thrown into the async generator frame by Python's `aclose()` machinery — it is NOT an `Exception` subclass and is NOT caught by any `except` clause. Only a `finally` block guarantees cleanup. Dedicated test: `test_generator_exit_triggers_finalize_and_aclose` (Coverage Map #2).
- `CancelledError` (Python 3.9+) is a `BaseException` subclass, also not caught by `except Exception`. Dedicated test: `test_cancelled_error_triggers_finalize_and_aclose` (Coverage Map #1).

### Edge Case: `discard_response` called with `None` upstream_response

- When `asyncio.timeout` fires before the first `proxy_request` call, `upstream_response` is `None` (hoisted variable, Design Decision 4). The `finally` block must check `if upstream_response is not None` before calling `discard_response()`, otherwise it would pass `None` to `discard_response` which expects an `httpx.Response`. Dedicated test: `test_timeout_before_proxy_request_skips_discard` (Coverage Map #9).

---

## Testing Paradigm

- **Framework:** pytest ≥9.0 + pytest-asyncio (strict mode). All async tests use `@pytest.mark.asyncio` decorator with `async def`.
- **Mocking:** `unittest.mock` only (`AsyncMock`, `MagicMock`, `patch`). **Do NOT use `pytest-mock` / `mocker` fixture** — it is intentionally absent from the project.
- **Zero hardcodes:** All configuration values must derive from `CanonicalConfig` at `tests/_canonical.py`. Use `CanonicalConfig.from_example_files()` for all config values. No hardcoded DB credentials, provider tokens, or API URLs.
- **Test directory:** Unit tests go in `tests/unit/services/`.
- **Test naming:** test files = `test_<snake_case>.py`, test classes = `class Test<Thing>:`, test functions = `test_<snake_case>`.
- **Group reference:** G1 = unit tests in `tests/unit/` excluding `tests/unit/config/`. Run via `poetry run pytest tests/unit/ --ignore=tests/unit/config -q --timeout=30`.
- **Gatekeeper:** Run `bash scripts/check-test-hardcodes.sh all` — must pass before commit. For boundary tests needing banned values, annotate with `# boundary: <reason>`.
- **Coverage:** No fail-under threshold. pytest-cov for informational coverage only.
- **Existing fixtures:** `tests/conftest.py` provides autouse `_set_config_vars_from_canonical` that monkeypatches env vars before every test. Tests do not need to set env vars manually.
- **Existing helpers:** `test_gateway_timeout.py` provides `_make_request_for_retry()`, `_make_provider()`, `_make_upstream_response()`, `_make_fail_result()`, `_make_success_result()`, and `_real_asyncio_sleep` — reuse these in new timeout tests. `test_gateway_service_stream_monitor.py` provides `mock_httpx_response` and `mock_logger` fixtures — reuse these in new stream monitor tests.
