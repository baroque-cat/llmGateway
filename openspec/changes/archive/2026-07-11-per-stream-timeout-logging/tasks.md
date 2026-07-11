## 1. Git & Environment

- [x] 1.1 Create a new git branch for this change: `git checkout -b per-stream-timeout-logging`
- [x] 1.2 Run the full test suite to establish a passing baseline: `make test`

## 2. H2 Connection: Add INFO log on per-stream timeout

- [x] 2.1 In `src/core/http2/h2_connection.py`, add a `logger.info()` call in the inner `except TimeoutError` handler (before `raise ReadTimeout`). Format: `f"Per-stream response timeout: stream_id={stream_id} stream_read={stream_read:.0f}s — sending RST_STREAM"`
- [x] 2.2 Run `poetry run ruff check src/core/http2/h2_connection.py && poetry run black src/core/http2/h2_connection.py`

## 3. Provider: Fix ReadTimeout detail to distinguish per-stream vs socket timeout

- [x] 3.1 In `src/providers/base.py`, modify the `httpx.ReadTimeout` detail string (lines 297-300) to conditionally report `stream_read=` or `read_timeout=` based on whether the exception message contains `"Per-stream timeout"`
- [x] 3.2 Run `poetry run ruff check src/providers/base.py && poetry run black src/providers/base.py`

## 4. Type Check & Lint

- [x] 4.1 Run `poetry run pyright` — verify no new type errors
- [x] 4.2 Run `poetry run ruff check src/` — verify no new lint violations
- [x] 4.3 Run `poetry run black --check src/` — verify formatting

## 5. Testing

- [x] 5.1 Read `test-plan.md` Delegation Groups section
- [x] 5.2 Delegate group `h2-connection-logging` to @Mr.Tester (scope: `tests/unit/core/http2/test_h2_connection.py`, G1)
- [x] 5.3 Delegate group `provider-error-detail` to @Mr.Tester (scope: `tests/unit/providers/test_base.py`, G1)
- [x] 5.4 Review @Mr.Tester reports and fix any source-level bugs discovered
- [x] 5.5 Re-delegate any groups affected by source fixes
- [x] 5.6 Run `make test` — all G1-G5 tests must pass
- [x] 5.7 Run `bash scripts/check-test-hardcodes.sh all` — verify zero-hardcodes compliance

<!--
  TEST DELEGATION PROTOCOL (followed by the apply-phase agent):

  1. Read test-plan.md → Delegation Groups section
  2. For EACH group listed, launch one @Mr.Tester subagent with:
     - The group's scope (file paths)
     - The group's scenario list from Coverage Map
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
-->

## 6. CI Verification

- [x] 6.1 Run `make ci` — full pipeline (lint + typecheck + test)
- [x] 6.2 Verify all G1-G5 test groups pass with no regressions
