## 1. Git & Environment

- [x] 1.1 Create a new git branch for this change: `git checkout -b add-per-stream-timeout`
- [x] 1.2 Run the full test suite to establish a passing baseline: `make test`

## 2. Schema: Add `stream_read` to `TimeoutConfig`

- [x] 2.1 Add `stream_read: float | None = Field(default=None, gt=0)` to `TimeoutConfig` in `src/config/schemas.py`
- [x] 2.2 Run `poetry run ruff check src/config/schemas.py && poetry run black src/config/schemas.py`

## 3. Config injection: Pass `stream_read` through `request.extensions`

- [x] 3.1 In `src/providers/base.py` `_send_proxy_request()`, add one line before `client.send()`: `request.extensions["stream_read"] = self.config.timeouts.stream_read`
- [x] 3.2 Run `poetry run ruff check src/providers/base.py && poetry run black src/providers/base.py`

## 4. H2 Connection: Per-stream timeout in `FixedHTTP2Connection`

- [x] 4.1 Add `import asyncio` to `src/core/http2/h2_connection.py`
- [x] 4.2 In `handle_async_request`, extract `stream_read` from `request.extensions` and compute effective timeout: `stream_read or request.extensions.get("timeout", {}).get("read", 120.0)`
- [x] 4.3 Wrap `await self._receive_response(request=request, stream_id=stream_id)` in `asyncio.wait_for(timeout=...)`
- [x] 4.4 Add inner `except TimeoutError:` block: call `self._h2_state.reset_stream(stream_id)`, `await self._write_outgoing_data(request)`, then `raise`
- [x] 4.5 Run `poetry run ruff check src/core/http2/h2_connection.py && poetry run black src/core/http2/h2_connection.py`

## 5. Config files: Update `defaults.py` and `example_full_config.yaml`

- [x] 5.1 Add `"stream_read": None` to the `timeouts` block in `src/config/defaults.py`
- [x] 5.2 Add missing `"pool_health_log_interval_sec": 60` to the `http_client` block in `src/config/defaults.py`
- [x] 5.3 Add `stream_read: 300.0` to `qwen-home` timeouts in `config/example_full_config.yaml` (match DashScope SDK `readTimeout`)
- [x] 5.4 Add explicit `timeouts` block (with default values) to `deepseek-main` in `config/example_full_config.yaml`
- [x] 5.5 Add explicit `gateway_policy` block (with retry enabled, matching other providers) to `deepseek-main` in `config/example_full_config.yaml`
- [x] 5.6 Update the "Using default health and gateway policies by omitting them" comment in `deepseek-main` section

## 6. CanonicalConfig: Add `stream_read` field

- [x] 6.1 Add `timeout_stream_read: float | None` field to `CanonicalConfig` in `tests/_canonical.py`
- [x] 6.2 Parse `stream_read` from `example_full_config.yaml` in `from_example_files()`, defaulting to `None`
- [x] 6.3 Add assertion for the new field in `tests/test_canonical_config.py`

## 7. Type Check & Lint

- [x] 7.1 Run `poetry run pyright` — verify no new type errors
- [x] 7.2 Run `poetry run ruff check src/` — verify no new lint violations
- [x] 7.3 Run `poetry run black --check src/` — verify formatting

## 8. Testing

- [x] 8.1 Read `test-plan.md` Delegation Groups section
- [x] 8.2 Delegate group `h2-connection-tests` to @Mr.Tester (scope: `tests/unit/core/http2/test_h2_connection.py`, G1)
- [x] 8.3 Delegate group `timeout-config-tests` to @Mr.Tester (scope: `tests/unit/config/test_timeout_config.py`, G2)
- [x] 8.4 Delegate group `stress-per-stream-tests` to @Mr.Tester (scope: `tests/stress/test_cascading_freeze.py`, G6)
- [x] 8.5 Delegate group `canonical-config-tests` to @Mr.Tester (scope: `tests/_canonical.py`, `tests/test_canonical_config.py`, G5)
- [x] 8.6 Review @Mr.Tester reports and fix any source-level bugs discovered
- [x] 8.7 Re-delegate any groups affected by source fixes
- [x] 8.8 Run `bash scripts/check-test-hardcodes.sh all` — verify zero-hardcodes compliance
- [x] 8.9 Run `make test` — all G1-G5 tests must pass
- [x] 8.10 Run `make test-slow` — G6 stress tests must pass

<!--
  TEST DELEGATION PROTOCOL (followed by the apply-phase agent):

  1. Read test-plan.md → Delegation Groups section
  2. For EACH group listed, launch one @Mr.Tester subagent with:
     - The group's scope (file paths)
     - The group's scenario list from Coverage Map
     - The Testing Paradigm docs from the project root:
       @TESTING.md, @TESTING-RUN.md, @TESTING-GUIDE.md, @TESTING-GATEKEEPER.md
     - Instruction: "Write or fix ONLY these specific tests. Report source bugs, don't fix them."
  3. Launch ALL groups IN PARALLEL (single message)
  4. After all testers return: fix any reported source bugs, re-delegate affected groups
  5. Repeat until all groups pass

  IMPORTANT: When delegating to @Mr.Tester subagents, the apply-phase agent MUST
  pass these testing paradigm documents to EACH tester:
  - @TESTING.md — documentation index and quick start
  - @TESTING-RUN.md — Makefile targets, G1-G6 process-isolation groups, timeout policy
  - @TESTING-GUIDE.md — Golden Rule (zero hardcodes via CanonicalConfig), boundary annotations, anti-patterns, compliance checklist
  - @TESTING-GATEKEEPER.md — gatekeeper script architecture, banned-pattern arrays, boundary lookback algorithm

  These documents define the mandatory testing conventions for the project.
  Without them, @Mr.Tester cannot produce compliant tests.

  Additionally, the apply-phase agent MUST also delegate tests for:
  - `src/providers/base.py` — `_send_proxy_request` injection of `stream_read` into
    `request.extensions`. Two new tests needed in `tests/unit/providers/test_base.py`:
    1. `test_send_proxy_request_injects_stream_read_when_set` — verify the field is
       placed in request.extensions before client.send()
    2. `test_send_proxy_request_injects_stream_read_none_when_not_set` — verify None
       is injected when stream_read is None
    These are NOT covered by the existing delegation groups and must be handled
    separately by the apply-phase agent or delegated as an additional task.
-->

## 9. CI Verification

- [x] 9.1 Run `make ci` — full pipeline (lint + typecheck + test)
- [x] 9.2 Verify all G1-G6 test groups pass with no regressions
