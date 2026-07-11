## Why

When the per-stream response header deadline fires in `FixedHTTP2Connection`,
there is no log at the transport layer. The only log message is emitted at
`ERROR` level by `_send_proxy_request` in `base.py`, and it **misattributes**
the timeout to `read_timeout=120s` — the socket-level timeout — rather than
the per-stream `stream_read` value that actually expired. This makes debugging
stream starvation incidents difficult: operators see a misleading timeout value
and have no visibility into which stream timed out or at what deadline.

## What Changes

- **Add an `INFO`-level log** in `h2_connection.py` when `TimeoutError` is
  caught from `asyncio.wait_for`. The message includes `stream_id` and the
  `stream_read` value, following the project's established single-line f-string
  log style.
- **Fix the `ReadTimeout` detail string** in `base.py` to distinguish between
  per-stream deadline exhaustion (`stream_read=Xs`) and socket-level read
  timeout (`read_timeout=Xs`). When the exception message contains
  `"Per-stream timeout"`, report the per-stream deadline; otherwise fall back
  to the existing socket-level detail.
- **No new config fields, no API changes, no required operator action.**

## Capabilities

### New Capabilities
- `per-stream-timeout-logging`: Per-stream timeout events are logged at `INFO`
  level at the transport layer (`h2_connection.py`) with stream id and timeout
  value, and the provider-level error detail in `base.py` correctly identifies
  per-stream vs socket-level timeout origin.

### Modified Capabilities
<!-- None — existing spec requirements are unchanged. -->

## Impact

- `src/core/http2/h2_connection.py` — one `logger.info()` call in the inner
  `except TimeoutError` handler, ~3 lines
- `src/providers/base.py` — conditional detail string for `httpx.ReadTimeout`,
  ~5 lines
- No new dependencies, no config changes, no API changes
