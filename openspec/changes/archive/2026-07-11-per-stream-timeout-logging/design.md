## Context

The per-stream response header deadline (`add-per-stream-timeout`) is enforced
in `FixedHTTP2Connection.handle_async_request()` via `asyncio.wait_for()`.
When the deadline fires, the inner `except TimeoutError` handler sends
`RST_STREAM`, flushes outgoing data, and raises `httpcore.ReadTimeout`. httpx
maps this to `httpx.ReadTimeout`, which is caught by `_send_proxy_request`'s
`except httpx.RequestError` block and logged at `ERROR` level.

**Current logging gap:** The `except TimeoutError` block in
`h2_connection.py:364-371` performs the recovery actions (`reset_stream`,
`write_outgoing_data`, `raise ReadTimeout`) but emits **zero log messages**.
The only log is in `base.py:312-319`, which generically logs any
`httpx.RequestError` at `ERROR` level with a detail string that reports
`read_timeout={read}s` — the socket-level timeout — regardless of whether the
actual trigger was the per-stream deadline.

## Goals / Non-Goals

**Goals:**
- Emit an `INFO`-level log when the per-stream deadline fires, with the
  `stream_id` and `stream_read` value visible to operators
- Fix the `ReadTimeout` detail in `_send_proxy_request` to distinguish
  per-stream deadline (`stream_read=Xs`) from socket-level timeout
  (`read_timeout=Xs`)
- Match existing log conventions: single-line f-string, module-level logger,
  no timestamp (provided by container), no ANSI colors

**Non-Goals:**
- Change log levels, formatting infrastructure, or the `component` filter
- Add metrics or structured logging (JSON)
- Add logging for the retry loop or other timeout types

## Decisions

### Decision 1: Log level — `INFO`

Per-stream timeout is a **designed, normal** operation of the starvation
defense mechanism. It is not an error — it is the feature working as intended.
The project uses `INFO` for equivalent operational events: retry progress
(`"Rotating key... Backoff Xs"`), pool health reports, and gateway access
logs. Using `INFO` keeps the per-stream timeout visible without polluting
the error channel.

**Alternative considered:** `WARNING` — rejected because the timeout is
expected behavior, not a sign of degradation. `ERROR` — rejected because
`_send_proxy_request` already logs the final error; duplicating at `ERROR`
would add noise without value.

### Decision 2: Log location — inner `except TimeoutError` in `h2_connection.py`

The inner handler has access to both `stream_id` (the timed-out stream) and
the `stream_read` value that expired. Logging here captures the event at the
moment of detection, before the exception is converted to `ReadTimeout` and
propagated. The outer `except BaseException` block runs cleanup and re-raises;
logging there would lose the timing of the original event.

**Format:**
```python
logger.info(
    "Per-stream response timeout: stream_id=%d stream_read=%.0fs — "
    "sending RST_STREAM",
    stream_id,
    stream_read,
)
```

This matches the project's single-line f-string convention (ref:
`StreamMonitor` line 282-285, `_send_proxy_request` line 312-318).

### Decision 3: Provider-level detail fix — inspect exception message

In `_send_proxy_request`, the `httpx.ReadTimeout` exception message is
`"Per-stream timeout reading response headers"` (set in `h2_connection.py`).
The handler checks for this substring to decide the detail string:

```python
# Existing (lines 297-300):
detail = f" — no data received (read_timeout={self.config.timeouts.read}s)"

# New:
if "Per-stream timeout" in str(e):
    detail = (
        f" — per-stream deadline exceeded "
        f"(stream_read={self.config.timeouts.stream_read}s)"
    )
else:
    detail = (
        f" — no data received "
        f"(read_timeout={self.config.timeouts.read}s)"
    )
```

**Alternative considered:** Adding a new exception subclass — rejected as
over-engineering for a log message. Checking the message string is the
lightest touch and requires zero changes to httpx or httpcore.

## Risks / Trade-offs

- **Log volume:** Under sustained stream starvation, the `INFO` log fires once
  per timed-out stream. This is bounded by the number of concurrent streams
  (typically ≤100) and is no more verbose than the existing `WARNING`-level
  retry attempt logs. → Acceptable.

- **Message-based detection fragility:** The `"Per-stream timeout"` substring
  check in `base.py` couples the detail string to the exception message text
  in `h2_connection.py`. If the message changes, the detail silently falls
  back to the socket-level string. → Mitigation: the message text is set
  in a single location (`h2_connection.py:370`) and covered by a unit test
  that verifies the detail string.
