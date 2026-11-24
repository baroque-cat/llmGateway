## Purpose

Attach a stable transport-phase classification to every failed upstream
attempt so retry, keeper, and guard logic can distinguish a dead tunnel from
a provider error without parsing log strings.

## Requirements

### Requirement: Every httpx transport exception is classified

The system SHALL map `httpx.RequestError` subclasses to
`TransportFailureClass`.

#### Scenario: Connect timeout

- **WHEN** `httpx.ConnectTimeout` is raised
- **THEN** `CheckResult.transport_class` SHALL be `connect_timeout`
- **AND** `CheckResult.error_reason` SHALL be `NETWORK_ERROR`
- **AND** `CheckResult.status_code` SHALL be 503

#### Scenario: Per-stream read timeout

- **WHEN** `httpx.ReadTimeout` is raised with `"Per-stream timeout"` in its text
- **THEN** the class SHALL be `stream_read_timeout`

#### Scenario: Ordinary read timeout

- **WHEN** `httpx.ReadTimeout` is raised without the per-stream marker
- **THEN** the class SHALL be `read_timeout`

#### Scenario: HTTP/2 pool saturation

- **WHEN** `httpx.LocalProtocolError` is raised
- **THEN** the class SHALL be `pool_saturated`
- **AND** the error reason SHALL remain `BAD_REQUEST` for backward compatibility
- **AND** the key SHALL NOT be penalized

#### Scenario: Unknown `RequestError`

- **WHEN** another `httpx.RequestError` subclass is raised
- **THEN** the class SHALL be `request_error`

### Requirement: Success and HTTP-status failures have no transport class

#### Scenario: Successful response

- **WHEN** the upstream returns 2xx
- **THEN** `transport_class` SHALL be `None`

#### Scenario: Provider 4xx/5xx response

- **WHEN** the upstream returns an HTTP error response
- **THEN** `transport_class` SHALL be `None`

### Requirement: Serialization is backward compatible

#### Scenario: `to_dict` without a transport class

- **WHEN** `CheckResult` has `transport_class = None`
- **THEN** `to_dict()` SHALL NOT include a `transport_class` key

#### Scenario: `to_dict` with a transport class

- **WHEN** `CheckResult` has a transport class
- **THEN** `to_dict()` SHALL include `transport_class` as its string value

### Requirement: Transport classes are observable

#### Scenario: Attempt metric

- **WHEN** an upstream attempt completes
- **THEN** `llm_gateway_upstream_attempts_total` SHALL increment with
  `provider` and `outcome` labels

#### Scenario: Transport failure metric

- **WHEN** an attempt has a non-null transport class
- **THEN** `llm_gateway_transport_failures_total` SHALL increment with
  `provider` and `transport_class` labels
