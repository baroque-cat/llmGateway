## ADDED Requirements

### Requirement: stream_read field in TimeoutConfig
`TimeoutConfig` SHALL include an optional `stream_read` field of type
`float | None` with default `None`. The field SHALL be validated with `gt=0`
when not `None`.

#### Scenario: stream_read accepts valid float
- **WHEN** the YAML config contains `timeouts: { stream_read: 30.0 }`
- **THEN** `provider_config.timeouts.stream_read` SHALL be `30.0`

#### Scenario: stream_read defaults to None
- **WHEN** a provider omits `stream_read` from its `timeouts` block
- **THEN** `provider_config.timeouts.stream_read` SHALL be `None`

#### Scenario: stream_read rejects zero
- **WHEN** the YAML config contains `timeouts: { stream_read: 0.0 }`
- **THEN** a Pydantic `ValidationError` SHALL be raised

#### Scenario: stream_read rejects negative
- **WHEN** the YAML config contains `timeouts: { stream_read: -5.0 }`
- **THEN** a Pydantic `ValidationError` SHALL be raised
