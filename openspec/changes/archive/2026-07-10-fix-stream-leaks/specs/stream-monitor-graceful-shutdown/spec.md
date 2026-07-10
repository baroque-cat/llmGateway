## ADDED Requirements

### Requirement: StreamMonitor finalizes on all exit paths
`StreamMonitor.__anext__()` SHALL guarantee that `_finalize_logging()` is called on
EVERY exit path from the method, including: normal chunk iteration completion
(`StopAsyncIteration`), upstream stream disconnect (`httpx.ReadError` → `GatewayStreamError`),
unexpected exceptions, task cancellation (`asyncio.CancelledError`), and async generator
cleanup (`GeneratorExit`). The guarantee SHALL be implemented via a `finally` block.

#### Scenario: CancelledError triggers aclose
- **WHEN** `StreamMonitor.__anext__()` is awaiting an upstream chunk and the
  task is cancelled (e.g., client disconnect triggers `CancelledError`)
- **THEN** `_finalize_logging()` SHALL be called
- **AND** `self.upstream_response.aclose()` SHALL be invoked
- **AND** the `CancelledError` SHALL propagate to the caller after cleanup

#### Scenario: GeneratorExit triggers aclose
- **WHEN** the async generator is closed via `aclose()` (throwing `GeneratorExit`
  into the generator frame), either explicitly or by Python's `async for` cleanup
- **THEN** `_finalize_logging()` SHALL be called
- **AND** `self.upstream_response.aclose()` SHALL be invoked

#### Scenario: Normal stream completion triggers aclose
- **WHEN** the upstream iterator exhausts normally (raises `StopAsyncIteration`)
- **THEN** `_finalize_logging()` SHALL be called exactly once
- **AND** `self.upstream_response.aclose()` SHALL be invoked

#### Scenario: ReadError triggers aclose then re-raises GatewayStreamError
- **WHEN** the upstream stream raises `httpx.ReadError` during chunk iteration
- **THEN** a `GatewayStreamError` with `error_reason=ErrorReason.STREAM_DISCONNECT`
  SHALL be raised to the caller
- **AND** `_finalize_logging()` SHALL be called before the re-raise

### Requirement: Idempotent finalization
`_finalize_logging()` SHALL be safe to call multiple times on the same `StreamMonitor`
instance. Only the first invocation SHALL execute the logging and `aclose()` logic;
subsequent invocations SHALL be no-ops.

#### Scenario: Double finalize is safe
- **WHEN** `_finalize_logging()` has already been called once
- **THEN** a second call SHALL return immediately without executing logging or `aclose()`

### Requirement: aclose failures are logged, not raised
If `self.upstream_response.aclose()` raises an exception during `_finalize_logging()`,
the exception SHALL be caught and logged at ERROR level. It SHALL NOT propagate to
the caller, to avoid masking any original exception that triggered the `finally` block.

#### Scenario: aclose raises in finally
- **WHEN** `_finalize_logging()` is called from a `finally` block (e.g., after
  `CancelledError`) and `upstream_response.aclose()` raises an exception
- **THEN** the exception SHALL be logged at ERROR level with `exc_info=True`
- **AND** the original `CancelledError` SHALL propagate to the caller
- **AND** no new exception SHALL be raised from `_finalize_logging()`
