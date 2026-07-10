## 1. Git & Environment

- [x] 1.1 Create a new git branch for this change: `git checkout -b fix-stream-leaks`
- [x] 1.2 Run the full test suite to establish a passing baseline: `make test`

## 2. StreamMonitor: Add `finally` block and `_finalized` guard (Bug #1)

- [x] 2.1 Add `self._finalized: bool = False` field to `StreamMonitor.__init__()` in `src/services/gateway/gateway_service.py`
- [x] 2.2 Add `if self._finalized: return` guard as first line of `_finalize_logging()`
- [x] 2.3 Set `self._finalized = True` after the guard in `_finalize_logging()`
- [x] 2.4 Wrap `await self.upstream_response.aclose()` in `_finalize_logging()` in `try/except Exception` with `logger.error(exc_info=True)`
- [x] 2.5 Rewrite `__anext__()`: remove `await self._finalize_logging()` calls from `except StopAsyncIteration` and `except httpx.ReadError` blocks (keep `raise` and `raise GatewayStreamError(...)` respectively)
- [x] 2.6 Remove the `except Exception` block entirely from `__anext__()` (Design Decision 3)
- [x] 2.7 Add `finally` block to `__anext__()`: `if not self._finalized: await self._finalize_logging()`
- [x] 2.8 Run `ruff check src/services/gateway/gateway_service.py` and `poetry run black src/services/gateway/gateway_service.py`

## 3. Timeout Handler: Close upstream_response in `finally` (Bug #2)

- [x] 3.1 Declare `upstream_response: httpx.Response | None = None` and `body_bytes: bytes | None = None` before the `try` block in `_handle_buffered_retryable_request()`
- [x] 3.2 Wrap the entire `async with asyncio.timeout(timeout_sec): ...` block in `try:`
- [x] 3.3 Add `except TimeoutError:` block (move existing handler from line 811)
- [x] 3.4 Add `finally:` block: check `if upstream_response is not None` → `try: await discard_response(upstream_response, body_bytes) except Exception: logger.error(... exc_info=True)`
- [x] 3.5 Run `ruff check src/services/gateway/gateway_service.py` and `poetry run black src/services/gateway/gateway_service.py`

## 4. Type Check & Lint

- [x] 4.1 Run `poetry run pyright` — verify no new type errors introduced
- [x] 4.2 Run `poetry run ruff check src/` — verify no new lint violations
- [x] 4.3 Run `poetry run black --check src/` — verify formatting

## 5. Testing

- [x] 5.1 Read `test-plan.md` Delegation Groups section
- [x] 5.2 Delegate group `stream-monitor-tests` to @Mr.Tester (scope: `tests/unit/services/test_gateway_service_stream_monitor.py`)
- [x] 5.3 Delegate group `timeout-handler-tests` to @Mr.Tester (scope: `tests/unit/services/test_gateway_timeout.py`)
- [x] 5.4 Review @Mr.Tester reports and fix any source-level bugs discovered
- [x] 5.5 Re-delegate any groups affected by source fixes
- [x] 5.6 Run `bash scripts/check-test-hardcodes.sh all` — verify zero-hardcodes compliance
- [x] 5.7 Run `make test` — all G1-G5 tests must pass

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

  IMPORTANT: When delegating to @Mr.Tester, the agent MUST pass these testing
  paradigm documents to each tester subagent:
  - @TESTING.md — documentation index and quick start
  - @TESTING-RUN.md — Makefile targets, G1-G6 process-isolation groups, timeout policy
  - @TESTING-GUIDE.md — Golden Rule (zero hardcodes via CanonicalConfig), boundary annotations, anti-patterns, compliance checklist
  - @TESTING-GATEKEEPER.md — gatekeeper script architecture, banned-pattern arrays, boundary lookback algorithm

  These documents define the mandatory testing conventions for the project.
  Without them, @Mr.Tester cannot produce compliant tests.
-->

## 6. CI Verification

- [x] 6.1 Run `make ci` — full pipeline (lint + typecheck + test)
- [x] 6.2 Verify all G1-G5 test groups pass with no regressions
