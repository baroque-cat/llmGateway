## ADDED Requirements

### Requirement: Per-stream timeout is primary defense, total is backstop
The gateway SHALL use the per-stream response header deadline (enforced by
`FixedHTTP2Connection` via `asyncio.wait_for`) as the **primary** defense against
stream starvation. The `asyncio.timeout(total)` deadline wrapping the retry loop
SHALL serve as the **backstop** — firing only when the per-stream timeout
itself fails to resolve the situation (e.g., all streams time out and retries
exhaust the total deadline).

#### Scenario: Per-stream timeout fires before total deadline
- **WHEN** a provider has `timeouts.total: 600` and `timeouts.read: 120`,
  and the upstream hangs without sending response headers
- **THEN** the per-stream timeout SHALL fire at approximately 120s
- **AND** the `NETWORK_ERROR` SHALL be returned to the retry loop
- **AND** the retry loop SHALL retry on a new stream
- **AND** the `asyncio.timeout(600)` SHALL NOT fire before retries are exhausted

#### Scenario: Total deadline fires when all retries time out
- **WHEN** a provider has `timeouts.total: 600` and `timeouts.read: 120`,
  and retries are configured but every attempt hits the per-stream timeout
- **THEN** approximately 5 per-stream timeouts (120s each) SHALL occur within the 600s window
- **AND** if retries are exhausted, the gateway SHALL return an error
- **AND** if retries are NOT exhausted, the `asyncio.timeout(600)` SHALL fire
  and return a 504 with structured error data
