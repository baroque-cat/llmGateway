## Context

The llmGateway Conductor uses HTTP/2 multiplexing — up to `max_concurrent_streams_per_connection` (default 5) concurrent streams share a single TCP connection via `FixedHTTP2Connection` with `NonBlockingSemaphore`. Each stream acquires a semaphore slot on send and releases it when the response is closed.

Two code paths bypass response closure, creating permanent semaphore leaks:

1. **`StreamMonitor.__anext__` (line 237-264)**: When a client disconnects mid-stream or `asyncio.timeout` fires, Starlette throws `CancelledError` (a `BaseException`) into the async generator. The three `except` blocks (`StopAsyncIteration`, `httpx.ReadError`, `Exception`) do NOT catch `BaseException` subclasses. `_finalize_logging()` → `aclose()` is never called. The semaphore slot is leaked permanently.

2. **`_handle_buffered_retryable_request` timeout handler (line 811-830)**: When `asyncio.timeout(600s)` fires, the `except TimeoutError` block returns a 504 JSONResponse without closing `upstream_response`. The variable is scoped inside the `while True` loop body and inaccessible in the except block.

The production logs show connections stuck at 5/5 for 29+ minutes, with only gateway restart clearing the leaked slots.

## Goals / Non-Goals

**Goals:**
- Guarantee `upstream_response.aclose()` is called on EVERY exit path from `StreamMonitor.__anext__`, including `CancelledError`, `GeneratorExit`, normal completion, and exceptions
- Guarantee upstream response closure when `asyncio.timeout` fires in `_handle_buffered_retryable_request`
- Prevent double-invocation of `_finalize_logging()` (idempotency guard)

**Non-Goals:**
- Adding per-stream timeouts to `FixedHTTP2Connection` (separate change)
- Adding `try/finally` around `provider.proxy_request()` in the retry loop (Bug #3, deferred)
- Per-host connection limits for DashScope (configuration change, not code fix)
- Any changes to `src/core/http2/`, `src/providers/`, `src/services/gateway/response_forwarder.py`

## Decisions

### Decision 1: `finally` block over `except BaseException`

**Chosen:** Add a `finally` block to `__anext__` that calls `_finalize_logging()` conditionally.

**Rationale:** A `finally` block executes on ALL exit paths (normal return, any exception, `CancelledError`, `GeneratorExit`) without needing to enumerate every `BaseException` subclass. This is the canonical Python pattern for guaranteed cleanup.

**Alternative considered:** Adding `except BaseException` alongside the existing `except Exception`. Rejected because: (1) duplicate cleanup code in two except blocks, (2) still doesn't cover `GeneratorExit` which is NOT caught by any except-clause (Python's async generator machinery handles `GeneratorExit` internally before except blocks execute), (3) less clean separation — the `finally` approach makes the "cleanup always happens" guarantee self-evident.

### Decision 2: `_finalized` guard flag

**Chosen:** Add `self._finalized: bool = False` field, checked at the top of `_finalize_logging()`.

**Rationale:** After the fix, when `StopAsyncIteration` is raised during `async for`, two paths reach `_finalize_logging()`: the `except StopAsyncIteration: raise` path triggers `finally` → first call. Then Python's async generator machinery calls `aclose()` on the generator, which may trigger `GeneratorExit` → `finally` → second call. The flag prevents double `aclose()`.

### Decision 3: Remove `except Exception` from `__anext__`

**Chosen:** Delete the `except Exception` block entirely.

**Rationale:** After adding `finally`, the `except Exception` block provides no additional value — `_finalize_logging()` is already called in `finally`. The only remaining purpose was the `logger.error(...)` line, which is unnecessary since the exception will be logged by FastAPI's exception handler. Removing this block simplifies the code and eliminates a maintenance point.

### Decision 4: Variable hoisting for timeout handler

**Chosen:** Declare `upstream_response: httpx.Response | None = None` and `body_bytes: bytes | None = None` before the `try` block that wraps the retry loop.

**Rationale:** The variables are currently scoped inside the `while True` body (line 644). Hoisting them to function-scope makes them accessible in the `finally` block. The `discard_response()` call in `finally` handles all cases safely — for success paths where the response was already forwarded or closed, `discard_response` is a no-op (body_bytes is not None when forwarded via `forward_buffered_body`/`forward_error_to_client`; `aclose()` on already-closed responses is safe).

### Decision 5: Wrap cleanup calls in try/except

**Chosen:** Wrap `aclose()` inside `_finalize_logging()` and `discard_response()` inside the timeout `finally` block in `try/except` with `logger.error(exc_info=True)`.

**Rationale:** In Python < 3.11, an exception raised inside a `finally` block masks any original exception that triggered the `finally`. Wrapping in `try/except` ensures: (1) original exceptions propagate correctly, (2) cleanup failures are logged but don't crash the request handler, (3) behavior is consistent across Python 3.10–3.14.

## Risks / Trade-offs

- **[Risk]** `_finalize_logging()` call in `finally` could mask original exception if `aclose()` raises and is not caught → **Mitigated**: `aclose()` is wrapped in `try/except` with logging
- **[Risk]** `discard_response()` in `finally` may close a stream that's still being used by `StreamingResponse` → **Mitigated**: `discard_response` only calls `aclose()` when `body_bytes is None`. For success paths where `StreamingResponse` is returned (line 669), `body_bytes` is indeed `None`, but `aclose()` on an already-closed response is a safe no-op in httpx. By the time the `finally` runs, the response has either been fully consumed or the client's `StreamingResponse` is still iterating — in the latter case, `aclose()` closes the underlying connection, which is acceptable since the client already received a response
- **[Risk]** Double-`aclose()` from `StopAsyncIteration` + `finally` → **Mitigated**: `_finalized` flag ensures exactly-one invocation
- **[Trade-off]** Removing `except Exception` + `logger.error(...)` means some unexpected exceptions during streaming won't have an explicit log line before the `finally` cleanup → Acceptable: the exception propagates to FastAPI's exception handler which logs it; the key invariant (`aclose()` is called) is preserved
