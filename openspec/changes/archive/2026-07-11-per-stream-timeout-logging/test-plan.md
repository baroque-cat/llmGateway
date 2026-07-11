# QA Strategy & Test Plan

## Coverage Map

<!-- 4 scenarios across 1 spec capability (per-stream-timeout-logging).
     Two requirements: transport-layer INFO log + provider-level detail
     disambiguation. Each scenario maps to exactly one test function in
     one of two existing test files. -->

| # | Spec Capability | Requirement | Scenario | Test File | Test Name | Group |
|---|---|---|---|---|---|---|
| 1 | per-stream-timeout-logging | Per-stream timeout logged at transport layer | Log emitted on per-stream timeout | `tests/unit/core/http2/test_h2_connection.py` | `test_per_stream_timeout_emits_info_log_with_stream_id_and_stream_read` | h2-connection-logging |
| 2 | per-stream-timeout-logging | Per-stream timeout logged at transport layer | No log when per-stream deadline is not configured | `tests/unit/core/http2/test_h2_connection.py` | `test_no_per_stream_timeout_log_when_stream_read_is_none` | h2-connection-logging |
| 3 | per-stream-timeout-logging | Provider error detail distinguishes per-stream from socket timeout | Per-stream deadline identified in error detail | `tests/unit/providers/test_base.py` | `test_read_timeout_with_per_stream_message_reports_stream_read_detail` | provider-error-detail |
| 4 | per-stream-timeout-logging | Provider error detail distinguishes per-stream from socket timeout | Socket-level timeout reported when per-stream not involved | `tests/unit/providers/test_base.py` | `test_read_timeout_logged_with_detail` (MODIFY existing) | provider-error-detail |

## Delegation Groups

<!-- Two non-overlapping groups. Each group owns exactly one test file.
      Both groups are in G1 (unit tests, run via `make test`). The files
      are in different directories and test different source modules
      (h2_connection.py vs base.py), so they can be delegated in
      parallel without conflict. -->

### Group: `h2-connection-logging`

**Scope:** `tests/unit/core/http2/test_h2_connection.py`

| Test File | Scenarios | Action |
|---|---|---|
| `tests/unit/core/http2/test_h2_connection.py` | 2 (scenarios #1–#2) + 1 risk-driven edge case | MODIFY (2 new test functions in existing `TestPerStreamTimeout` class + 1 risk-driven edge case test) |

**Description:** Validates the `INFO`-level log emitted by `FixedHTTP2Connection.handle_async_request()` when the per-stream deadline fires in the inner `except TimeoutError` handler (lines 363–372 of `src/core/http2/h2_connection.py`).

- **Log emitted on timeout (scenario #1):** `_receive_response` is mocked to hang beyond the `stream_read` deadline. Asserts `logger.info` is called exactly once with a message containing `"Per-stream response timeout"`, the `stream_id` integer, and the `stream_read` float value. Asserts the log is emitted BEFORE `ReadTimeout` is raised by verifying `logger.info` was called before the `pytest.raises(ReadTimeout)` block exits. Uses `patch("src.core.http2.h2_connection.logger")` to capture the call.
- **No log when stream_read is None (scenario #2):** `request.extensions["stream_read"]` is `None`. `_receive_response` returns immediately. Asserts `logger.info` is NOT called for any per-stream timeout message (the `asyncio.wait_for` block is never entered). Reuses the existing `test_stream_read_none_no_per_stream_timeout` setup pattern but adds logger assertions.
- **Risk-driven edge case — log fires exactly once (Risk: Log volume):** Verifies that the `INFO` log fires exactly once per timed-out stream, not duplicated by the outer `except BaseException` → `_response_closed` cleanup path. Asserts `mock_logger.info.assert_called_once()` after `pytest.raises(ReadTimeout)`.

All tests use the existing `_make_conn()` and `_make_request()` helpers from `TestPerStreamTimeout`. The logger is patched via `with patch("src.core.http2.h2_connection.logger") as mock_logger:` — note that the module-level logger in `h2_connection.py` is `logging.getLogger("httpcore.http2")`, but it is patched at the module attribute level (`src.core.http2.h2_connection.logger`), consistent with how `test_base.py` patches `src.providers.base.logger`. Timeout values use small deltas (0.05s) for fast unit-test execution, consistent with existing `TestPerStreamTimeout` tests. Config-derived values (e.g., `cfg.timeout_read`) use `CanonicalConfig.from_example_files()`.

---

### Group: `provider-error-detail`

**Scope:** `tests/unit/providers/test_base.py`

| Test File | Scenarios | Action |
|---|---|---|
| `tests/unit/providers/test_base.py` | 2 (scenario #3 NEW + scenario #4 MODIFY) + 1 risk-driven edge case | MODIFY (1 new test function in existing `TestEnhancedNetworkErrorLogging` class + 1 modification to existing test + 1 risk-driven edge case test) |

**Description:** Validates the conditional detail string in `_send_proxy_request`'s `except httpx.RequestError` handler (lines 297–300 of `src/providers/base.py`) that distinguishes per-stream deadline exhaustion from socket-level read timeout.

- **Per-stream detail (scenario #3, NEW):** Mocks `client.send` to raise `httpx.ReadTimeout("Per-stream timeout reading response headers")` — the exact message text set in `h2_connection.py:370`. The provider is configured with a non-None `stream_read` value (from `CanonicalConfig.from_example_files().timeout_read`, since `cfg.timeout_stream_read` is `None` in the canonical config). Asserts the `logger.error` message contains `"stream_read="` and `"per-stream deadline exceeded"`, and does NOT contain `"read_timeout="` or `"no data received"`.
- **Socket-level detail (scenario #4, MODIFY existing):** The existing `test_read_timeout_logged_with_detail` test mocks `httpx.ReadTimeout("read timeout")` — a message that does NOT contain `"Per-stream timeout"`. The existing assertion `"no data received" in log_message` still passes (the socket-level detail string is unchanged in content). The modification ADDS an assertion for `"read_timeout=" in log_message` to verify the correct detail format that distinguishes it from the per-stream `stream_read=` path. This strengthens the test to fail if the wrong branch were taken.
- **Risk-driven edge case — silent fallback on message drift (Risk: Message-based detection fragility):** Mocks `client.send` to raise `httpx.ReadTimeout("per-stream timeout")` — lowercase, does NOT contain the capitalized `"Per-stream timeout"` substring. Asserts the detail falls back to the socket-level `read_timeout=` string, proving the substring check is case-sensitive and that message drift silently falls back to the socket-level path (the designed behavior per design.md Risk mitigation).

All tests use the existing `TestEnhancedNetworkErrorLogging._create_provider()` helper and `patch("src.providers.base.logger")` pattern. The new per-stream detail test uses `TestSendProxyRequestChangedContract._create_provider_with_config(stream_read=cfg.timeout_read)` to set a non-None `stream_read` value, since `TestEnhancedNetworkErrorLogging._create_provider()` uses default config where `stream_read=None`.

---

## Test Modifications

<!-- Existing tests that need updating due to this change. Each modification
      references the spec scenario or design decision that motivates it. -->

### File: `tests/unit/core/http2/test_h2_connection.py`

| Change | Reason |
|---|---|
| **NEW** `test_per_stream_timeout_emits_info_log_with_stream_id_and_stream_read` in `TestPerStreamTimeout` class: Patches `src.core.http2.h2_connection.logger` with a `MagicMock`. Sets up the same hanging `_receive_response` mock as `test_per_stream_timeout_fires_releases_semaphore_and_survives` with `stream_read=0.05`. Calls `await conn.handle_async_request(request)` inside `pytest.raises(ReadTimeout)`. After the exception, asserts: (1) `mock_logger.info.assert_called_once()` — exactly one INFO log; (2) the log message (first positional arg or `args[0]`) contains `"Per-stream response timeout"`; (3) the log call args include the `stream_id` (1) and `stream_read` (0.05) values; (4) `mock_logger.error.assert_not_called()` and `mock_logger.warning.assert_not_called()` — confirming INFO level, not ERROR/WARNING. To verify the log is emitted BEFORE `ReadTimeout` is raised, the test uses a `call_order` list: a `side_effect` on `mock_logger.info` appends `"info_log"` and a `side_effect` on `conn._h2_state.reset_stream` appends `"reset_stream"` — then asserts `call_order[0] == "info_log"` and `call_order[1] == "reset_stream"`, proving the log precedes the RST_STREAM + raise sequence. | Scenario #1: "Log emitted on per-stream timeout" — spec requires INFO level, `stream_id`, `stream_read` value, and emission before `ReadTimeout`. Design Decision 1 (INFO level) and Decision 2 (log location: inner `except TimeoutError`). |
| **NEW** `test_no_per_stream_timeout_log_when_stream_read_is_none` in `TestPerStreamTimeout` class: Uses the same setup as the existing `test_stream_read_none_no_per_stream_timeout` (stream_read=None, `_receive_response` returns immediately). Patches `src.core.http2.h2_connection.logger`. Calls `await conn.handle_async_request(request)` and asserts the response is returned normally. Then asserts `mock_logger.info.assert_not_called()` — no per-stream timeout log was emitted because the `asyncio.wait_for` block was never entered (the `else` branch called `_receive_response` directly). | Scenario #2: "No log when per-stream deadline is not configured" — spec requires no per-stream timeout log when `stream_read` is `None`. The code path does not enter the `asyncio.wait_for` block, so no log is emitted. |
| **NEW** `test_per_stream_timeout_log_emitted_exactly_once` in `TestPerStreamTimeout` class (risk-driven): Uses the same hanging `_receive_response` setup with `stream_read=0.05`. Patches the logger. After `pytest.raises(ReadTimeout)`, asserts `mock_logger.info.call_count == 1` — the log fires exactly once, not duplicated by the outer `except BaseException` → `_response_closed` cleanup path. | Risk: "Log volume" from design.md — under sustained stream starvation, the INFO log fires once per timed-out stream. This test verifies the outer `except BaseException` handler (which runs `_response_closed`) does NOT emit a duplicate log. |

### File: `tests/unit/providers/test_base.py`

| Change | Reason |
|---|---|
| **NEW** `test_read_timeout_with_per_stream_message_reports_stream_read_detail` in `TestEnhancedNetworkErrorLogging` class: Creates a provider with `stream_read` set to a non-None canonical value via `TestSendProxyRequestChangedContract._create_provider_with_config(stream_read=CanonicalConfig.from_example_files().timeout_read)`. Mocks `client.send` to raise `httpx.ReadTimeout("Per-stream timeout reading response headers")` — the exact message from `h2_connection.py:370`. Patches `src.providers.base.logger`. Calls `await provider._send_proxy_request(mock_client, mock_request)`. Asserts: (1) `mock_logger.error.assert_called_once()`; (2) the log message contains `"stream_read="` and `"per-stream deadline exceeded"`; (3) the log message does NOT contain `"read_timeout="` or `"no data received"`; (4) `check_result.error_reason == ErrorReason.NETWORK_ERROR`; (5) `response.status_code == 503`; (6) `body_bytes is None`. | Scenario #3: "Per-stream deadline identified in error detail" — spec requires `stream_read=Xs` in the detail string when the exception message contains `"Per-stream timeout"`. Design Decision 3: inspect exception message for the `"Per-stream timeout"` substring. |
| **MODIFY** `test_read_timeout_logged_with_detail` (line 1616) in `TestEnhancedNetworkErrorLogging` class: The existing test mocks `httpx.ReadTimeout("read timeout")` — the message does NOT contain `"Per-stream timeout"`, so the socket-level detail path is taken. The existing assertion `"no data received" in log_message` still passes (the socket-level detail string content is unchanged). The modification ADDS: `assert "read_timeout=" in log_message` — verifying the detail format includes the `read_timeout=Xs` value, which distinguishes it from the per-stream `stream_read=` path. Also ADDS: `assert "stream_read=" not in log_message` and `assert "per-stream deadline" not in log_message` — negative assertions proving the per-stream path was NOT taken. | Scenario #4: "Socket-level timeout reported when per-stream not involved" — spec requires `read_timeout=Xs` in the detail string when the exception message does NOT contain `"Per-stream timeout"`. The existing test only checks `"no data received"` which is present in the socket-level path but does not verify the `read_timeout=` format or exclude the per-stream path. Design Decision 3: backward-compatible fallback to `read_timeout=Xs`. |
| **NEW** `test_read_timeout_substring_check_is_case_sensitive` in `TestEnhancedNetworkErrorLogging` class (risk-driven): Creates a provider with `stream_read` set to a non-None value. Mocks `client.send` to raise `httpx.ReadTimeout("per-stream timeout reading response headers")` — lowercase `"per-stream timeout"`, does NOT contain the capitalized `"Per-stream timeout"` substring. Patches `src.providers.base.logger`. Asserts the log message contains `"read_timeout="` and `"no data received"` (socket-level fallback), NOT `"stream_read="` or `"per-stream deadline"`. | Risk: "Message-based detection fragility" from design.md — the `"Per-stream timeout"` substring check is case-sensitive. If the message text changes (e.g., lowercase, different wording), the detail silently falls back to the socket-level string. This test verifies the case sensitivity and the silent fallback behavior, which is the designed mitigation per design.md. |
| **VERIFIED — NO CHANGE NEEDED** `test_other_request_errors_still_map_to_network_error` (line 1437) in `TestSendProxyRequestChangedContract` class: This parametrized test includes `httpx.ReadTimeout` with message `"test error"` (does NOT contain `"Per-stream timeout"`). It only asserts `ErrorReason.NETWORK_ERROR`, `status_code == 503`, `body_bytes is None` — no detail string assertions. The test continues to pass as-is because the socket-level path is taken (message does not match) and the asserted invariants (NETWORK_ERROR, 503, None) are unchanged. No modification needed. | Scenario #4 (indirectly): The parametrized test verifies that `httpx.ReadTimeout` maps to `NETWORK_ERROR` regardless of the detail string. The detail string change does not affect these invariants. Verified, no update required. |

---

## Risks & Edge Cases

<!-- Risks from design.md Risks / Trade-offs section that need dedicated
      test coverage. Each risk maps to a concrete test. -->

### Risk: Log volume under sustained stream starvation

- **Source:** design.md Risks / Trade-offs, bullet 1.
- **Description:** Under sustained stream starvation, the `INFO` log fires once per timed-out stream. This is bounded by the number of concurrent streams (typically ≤100). The risk is that the outer `except BaseException` → `_response_closed` cleanup path might emit a duplicate log, doubling the volume.
- **Mitigation in code:** The `logger.info()` call is placed in the inner `except TimeoutError` handler only (design.md Decision 2). The outer `except BaseException` block runs `_response_closed` for cleanup but does not log. The log is emitted once, before the `ReadTimeout` is raised.
- **Dedicated test:** `test_per_stream_timeout_log_emitted_exactly_once` (Group: `h2-connection-logging`) — patches the logger, triggers the per-stream timeout, and asserts `mock_logger.info.call_count == 1` after `pytest.raises(ReadTimeout)`. This proves the outer cleanup path does not duplicate the log.

### Risk: Message-based detection fragility

- **Source:** design.md Risks / Trade-offs, bullet 2.
- **Description:** The `"Per-stream timeout"` substring check in `base.py` couples the detail string to the exception message text in `h2_connection.py`. If the message changes (e.g., different capitalization, wording), the detail silently falls back to the socket-level `read_timeout=Xs` string. This is the designed behavior, but the coupling must be tested to catch message drift.
- **Mitigation in code:** The message text is set in a single location (`h2_connection.py:370`: `"Per-stream timeout reading response headers"`). The substring check in `base.py` looks for `"Per-stream timeout"` (capital P, capital S, capital T). Design.md states: "Mitigation: the message text is set in a single location and covered by a unit test that verifies the detail string."
- **Dedicated tests:**
  - `test_read_timeout_with_per_stream_message_reports_stream_read_detail` (Group: `provider-error-detail`, Coverage Map #3) — uses the EXACT message text from `h2_connection.py:370` and verifies the per-stream detail path is taken. If the message text in `h2_connection.py` changes, this test would need updating — making the coupling visible.
  - `test_read_timeout_substring_check_is_case_sensitive` (Group: `provider-error-detail`, risk-driven) — uses a lowercase variant `"per-stream timeout"` and verifies the socket-level fallback is taken. This proves the check is case-sensitive and documents the silent-fallback behavior.

### Edge Case: Log emitted before ReadTimeout is raised

- **Source:** Scenario #1: "the log message SHALL be emitted before `ReadTimeout` is raised."
- **Description:** The spec requires the `INFO` log to be emitted before the `ReadTimeout` exception is raised. If the log were emitted after the raise (e.g., in the outer `except BaseException` block), it would lose the timing context and the `stream_id` / `stream_read` values might not be in scope.
- **Mitigation in code:** The `logger.info()` call is the first statement in the inner `except TimeoutError` handler, before `reset_stream`, `_write_outgoing_data`, and `raise ReadTimeout` (design.md Decision 2).
- **Dedicated test:** `test_per_stream_timeout_emits_info_log_with_stream_id_and_stream_read` (Group: `h2-connection-logging`, Coverage Map #1) — uses a `call_order` list with `side_effect` callbacks on `mock_logger.info` (appends `"info_log"`) and `conn._h2_state.reset_stream` (appends `"reset_stream"`). Asserts `call_order[0] == "info_log"` and `call_order[1] == "reset_stream"`, proving the log precedes the RST_STREAM + raise sequence.

---

## Testing Paradigm

- **Framework:** pytest ≥9.0 + pytest-asyncio (strict mode). All async tests use `@pytest.mark.asyncio` decorator with `async def`. No auto-detection.
- **Mocking:** `unittest.mock` only (`AsyncMock`, `MagicMock`, `patch`). **Do NOT use `pytest-mock` / `mocker` fixture** — it is intentionally absent from the project.
- **Zero hardcodes:** All configuration values must derive from `CanonicalConfig` at `tests/_canonical.py`. Use `CanonicalConfig.from_example_files()` for all config values. For the per-stream detail test, `cfg.timeout_read` (120.0) is used as the `stream_read` value because `cfg.timeout_stream_read` is `None` in the canonical config — this follows the same pattern as the existing `test_send_proxy_request_injects_stream_read_into_extensions` test. Test-local timing values (e.g., `stream_read=0.05` for triggering fast timeouts in `h2_connection` tests) are not config values and are not flagged by the gatekeeper.
- **Logger patching:** Patch the module-level logger attribute, not the `logging.getLogger()` call. Use `with patch("src.core.http2.h2_connection.logger") as mock_logger:` for transport-layer tests and `with patch("src.providers.base.logger") as mock_logger:` for provider-level tests. This is consistent with the existing `TestEnhancedNetworkErrorLogging` tests.
- **Test directories:**
  - `tests/unit/core/http2/` — G1 unit tests (run via `make test` or `poetry run pytest tests/unit/core/http2/ -q --timeout=30`)
  - `tests/unit/providers/` — G1 unit tests (run via `make test` or `poetry run pytest tests/unit/providers/ -q --timeout=30`)
- **Test naming:** test files = `test_<snake_case>.py`, test classes = `class Test<Thing>:`, test functions = `test_<snake_case>`.
- **Markers:**
  - `@pytest.mark.asyncio` — all async tests
  - No `@pytest.mark.slow` — all tests in this plan are unit tests (G1)
- **Group reference:**
  - G1 = unit tests in `tests/unit/` excluding `tests/unit/config/`
  - Both delegation groups (`h2-connection-logging`, `provider-error-detail`) are in G1
- **Gatekeeper:** Run `bash scripts/check-test-hardcodes.sh all` — must exit 0 before commit. No boundary annotations needed — all config values derive from `CanonicalConfig`.
- **Coverage:** No fail-under threshold. pytest-cov for informational coverage only.
- **Existing fixtures:** `tests/conftest.py` provides autouse `_set_config_vars_from_canonical` that monkeypatches all 17 env vars before every test. Tests do not need to set env vars manually.
- **Existing helpers:**
  - `test_h2_connection.py` provides `TestPerStreamTimeout._make_conn()` (via `TestFixedHTTP2Connection._make_conn()`) and `TestPerStreamTimeout._make_request()` — reuse and extend for new logging tests.
  - `test_base.py` provides `TestEnhancedNetworkErrorLogging._create_provider()` and `TestSendProxyRequestChangedContract._create_provider_with_config()` — reuse for new detail-string tests.
- **Quality gates:** All changes must pass: `poetry run pyright` (strict on `src/core/`, `src/config/`), `poetry run ruff check src/ tests/`, `poetry run black --check src/ tests/`, `make test`, `bash scripts/check-test-hardcodes.sh all`.
