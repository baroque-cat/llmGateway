## Context

The gateway uses HTTP/2 multiplexing with `FixedHTTP2Connection` and `NonBlockingSemaphore`. The existing `httpx.Timeout(read=120)` timeout is enforced at the socket level — `anyio.fail_after(120)` wraps a single `socket.receive()` call. When multiple H2 streams share one TCP connection and some streams are active (receiving data), the socket-level timer resets on every `receive()` that returns data for any stream. A starved stream (server never sends response headers) waits indefinitely in the `while not self._events.get(stream_id)` loop.

Evidence: `docs/CASCADING_FREEZE_EVIDENCE.md` Test 3 proves that with `read_timeout=3s` shorter than the `delay=5s`, zero timeouts fire because drip-feed chunks every 500ms keep the socket alive. The only deadline that eventually fires is the gateway-level `asyncio.timeout(600)`.

The `fix-stream-leaks` change (archived) fixed permanent semaphore leaks from `CancelledError` but explicitly deferred per-stream timeouts as a non-goal.

## Goals / Non-Goals

**Goals:**
- Add per-stream deadline for the response-header-wait phase in `FixedHTTP2Connection`
- Make the deadline configurable per-provider via a new `stream_read` field (opt-in — per-stream deadline only when explicitly set, else socket-level `read` remains)
- Pass the value through the existing `request.extensions` mechanism
- Fix config staleness: add missing blocks to `example_full_config.yaml` and `defaults.py`
- Semaphore and `_events` cleanup must work correctly on timeout

**Non-Goals:**
- Per-stream timeout for body-streaming phase (`_receive_response_body`) — header-only this iteration
- Per-host connection limits (DashScope `maximumAsyncRequestsPerHost=32`) — config concern, not code
- Any changes to `src/core/http2/pool.py` or `transport.py`

## Decisions

### Decision 1: New `stream_read` field rather than repurposing `read`

**Chosen:** Add `stream_read: float | None = None` to `TimeoutConfig`, default `None` → no per-stream deadline (socket-level `read` remains as backstop).

**Rationale:** Separating socket-level and stream-level timeouts allows independent tuning. `read=120` serves as socket timeout (protects against complete silence). `stream_read=300` for DashScope matches their SDK default without affecting the socket timeout. If `stream_read is None`, behavior is unchanged — per-stream timeout uses `read` value.

**Alternative considered:** Repurpose `read` directly (no new field). Rejected because: cannot independently tune socket vs stream timeouts; reducing `read` to detect overload faster would also reduce socket timeout, breaking slow-but-active streams.

### Decision 2: Pass through `request.extensions`

**Chosen:** Inject `stream_read` into `request.extensions` in `_send_proxy_request` (one line before `client.send()`), read it in `handle_async_request`.

**Rationale:** `request.extensions` is the existing mechanism for passing per-request metadata through the httpx → httpcore chain. No new parameter plumbing through `HttpClientFactory`, `CapacityAwareHttp2Transport`, `CapacityAwareHttp2Pool`, `CapacityAwareHTTPConnection` — a single dict key is sufficient. Existing code already reads `request.extensions["timeout"]` in the upstream httpcore `_read_incoming_data`.

### Decision 3: `asyncio.wait_for` on `_receive_response` only

**Chosen:** Wrap only the `_receive_response` call, not the entire `handle_async_request`.

**Rationale:** The blocking point is `_receive_response` → `_receive_stream_event` → `while not self._events.get(stream_id)` loop. Wrapping only this call: (1) produces a clean `TimeoutError` from `asyncio.wait_for`, (2) falls into the existing `except BaseException` → `_response_closed` cleanup path, (3) does not interfere with the `_send_request_headers`/`_send_request_body` phases which have their own httpx timeouts.

### Decision 4: RST_STREAM before raising ReadTimeout

**Chosen:** In the inner `except TimeoutError` handler (before the outer `except BaseException`), explicitly call `self._h2_state.reset_stream(stream_id)` + `await self._write_outgoing_data(request)`, then raise `httpcore.ReadTimeout` (mapped to `httpx.ReadTimeout` by the transport).

**Rationale:** Sending `RST_STREAM` notifies the server the stream is abandoned, preventing server-side resource leaks and phantom stream accumulation in h2's state (the desync bug fixed in http2-stream-desync-fix). The outer `except BaseException` → `_response_closed` will also call `reset_stream` (line 103-109 of h2_connection.py) via its `stream_was_reset` check, but doing it explicitly in the inner handler makes intent clear and guarantees the reset happens before the semaphore release.  Raising `httpcore.ReadTimeout` (not the raw `TimeoutError` from `asyncio.wait_for`) ensures httpx maps it to `httpx.ReadTimeout`, which is a subclass of `httpx.RequestError` — caught by the provider's existing error handling in `_send_proxy_request`.

### Decision 5: Default `stream_read=None` means no per-stream deadline (socket-level `read` remains as backstop)

**Chosen:** `None` is the default. The per-stream deadline (`asyncio.wait_for`) is **only** applied when `stream_read` is explicitly set to a non-`None` value. When `None`, `_receive_response` is called directly without wrapping — the socket-level `read` timeout remains as the only backstop, preserving the original behavior.

**Rationale:** Using `read` as the `asyncio.wait_for` timeout is NOT equivalent to the socket-level `read` timeout. The socket-level timeout resets on each `socket.receive()`, so it does not fire when active streams keep the socket busy. `asyncio.wait_for(read)` fires after `read` seconds regardless of socket activity — breaking backward compatibility for providers without explicit `stream_read` (proven by the existing `test_read_timeout_silence_with_drip_feed` stress test).  Making `stream_read` an explicit opt-in (no per-stream deadline by default) preserves backward compatibility. Providers that need the feature set `stream_read` explicitly (e.g., qwen-home: 300 to match DashScope SDK).

## Risks / Trade-offs

- **[Risk]** Per-stream timeout fires during legitimate model "thinking" (models that send no headers until thinking completes) → **Mitigated**: The timeout only wraps `_receive_response` (headers phase), not body streaming. If the server sends 200 OK immediately (OpenAI-compatible pattern), the timer stops and thinking happens during body streaming — no timeout. If the server delays headers, `stream_read` can be set high (300s for DashScope) or even left at `read` default (120s). The DashScope evidence (`dashscope_sdk_time.md`) shows their own `readTimeout=300s` and `connectTimeout=120s`, suggesting they expect potentially long header-wait periods.
- **[Risk]** `stream_read` injection in `_send_proxy_request` might interfere with httpx internals → **Mitigated**: `request.extensions` is explicitly designed as an extension point. httpx preserves unknown keys. The key `"stream_read"` does not collide with any httpx internal key.
- **[Risk]** Timeout during `_write_outgoing_data` after `reset_stream` could leave the stream in an inconsistent state → **Mitigated**: The `try/except` in `_response_closed` lines 103-109 already handles `NoSuchStreamError` and `ProtocolError` from `reset_stream`. Even if `_write_outgoing_data` fails, the outer `except BaseException` + `AsyncShieldCancellation` ensures `_response_closed` runs and the semaphore is released.
- **[Trade-off]** The socket-level `read` timeout still exists and can fire independently (killing the entire connection) if the socket is silent for `read` seconds → This is acceptable as a backstop; the per-stream timeout fires first in the common case (active socket, starved stream).
