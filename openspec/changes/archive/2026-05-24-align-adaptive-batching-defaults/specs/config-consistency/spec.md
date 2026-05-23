## ADDED Requirements

### Requirement: AdaptiveBatchingConfig default values are consistent across config tiers
The `AdaptiveBatchingConfig` Pydantic model's `Field(default=…)` values SHALL match the corresponding values in `src/config/defaults.py` and `config/example_full_config.yaml`. Specifically, `start_batch_size` SHALL default to `10` and `start_batch_delay_sec` SHALL default to `30.0` at all three tiers of the default system.

#### Scenario: Pydantic default matches defaults.py
- **WHEN** an `AdaptiveBatchingConfig` is instantiated with no explicit arguments
- **THEN** `start_batch_size` SHALL equal `10`
- **AND** `start_batch_delay_sec` SHALL equal `30.0`

#### Scenario: Pydantic default matches example_full_config.yaml
- **WHEN** a user-provided `worker_health_policy.adaptive_batching` section in YAML includes only `start_batch_size` and `start_batch_delay_sec` with values `10` and `30.0`
- **THEN** the resulting `AdaptiveBatchingConfig` SHALL have `start_batch_size == 10` and `start_batch_delay_sec == 30.0`

### Requirement: HealthPolicyConfig default factory produces consistent AdaptiveBatchingConfig
When `HealthPolicyConfig()` is created without an explicit `adaptive_batching` argument, the `default_factory` SHALL produce an `AdaptiveBatchingConfig` with `start_batch_size == 10` and `start_batch_delay_sec == 30.0`.

#### Scenario: HealthPolicyConfig without explicit adaptive_batching
- **WHEN** `HealthPolicyConfig()` is instantiated with no arguments
- **THEN** `adaptive_batching` SHALL be a non-null `AdaptiveBatchingConfig` instance
- **AND** `adaptive_batching.start_batch_size` SHALL equal `10`
- **AND** `adaptive_batching.start_batch_delay_sec` SHALL equal `30.0`

### Requirement: Bounds validator accepts new default values
The `check_bounds` model validator on `AdaptiveBatchingConfig` SHALL accept `start_batch_size=10` (which SHALL be within `[min_batch_size=5, max_batch_size=50]`) and `start_batch_delay_sec=30.0` (which SHALL be within `[min_batch_delay_sec=3.0, max_batch_delay_sec=120.0]`).

#### Scenario: New defaults pass bounds validation
- **WHEN** `AdaptiveBatchingConfig(start_batch_size=10, start_batch_delay_sec=30.0)` is validated
- **THEN** no `ValidationError` SHALL be raised
