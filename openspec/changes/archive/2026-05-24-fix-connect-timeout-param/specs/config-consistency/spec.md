# config-consistency (delta)

## ADDED Requirements

### Requirement: DatabasePoolConfig timeout field is consistent across config tiers
The `DatabasePoolConfig` Pydantic model SHALL expose a `timeout` field (not `connect_timeout`) with `Field(default=60.0, gt=0)`. This field name SHALL match the `timeout` parameter in `asyncpg.connect()`. The default value of `60.0` SHALL be consistent across all three tiers of the default system: Pydantic `Field(default=…)`, `src/config/defaults.py`, and `config/example_full_config.yaml`.

#### Scenario: Pydantic default matches defaults.py
- **WHEN** a `DatabasePoolConfig` is instantiated with no explicit arguments
- **THEN** `timeout` SHALL equal `60.0`
- **AND** `command_timeout` SHALL equal `30.0`

#### Scenario: Pydantic default matches example_full_config.yaml
- **WHEN** a user-provided `database.pool` section in YAML includes `timeout: 60.0` and `command_timeout: 30.0`
- **THEN** the resulting `DatabasePoolConfig` SHALL have `timeout == 60.0` and `command_timeout == 30.0`

#### Scenario: Custom timeout value propagates correctly
- **WHEN** a user-provided `database.pool` section in YAML includes `timeout: 10.0`
- **THEN** the resulting `DatabasePoolConfig` SHALL have `timeout == 10.0`

### Requirement: DatabasePoolConfig timeout field name matches asyncpg API
The `timeout` parameter in `DatabasePoolConfig` SHALL be forwarded to `asyncpg.create_pool()` as the `timeout` keyword argument, which maps to `asyncpg.connect(timeout=...)`. The parameter name SHALL NOT be `connect_timeout`.

#### Scenario: init_db_pool forwards timeout to asyncpg.create_pool
- **WHEN** `database.init_db_pool(dsn, timeout=10.0)` is called
- **THEN** `asyncpg.create_pool` SHALL be invoked with the keyword argument `timeout=10.0`

#### Scenario: Timeout parameter reaches asyncpg.connect via create_pool
- **WHEN** `asyncpg.create_pool(timeout=10.0)` is called with a real asyncpg installation
- **THEN** no `TypeError` SHALL be raised (the `timeout` keyword SHALL be recognized by `asyncpg.connect()`)

### Requirement: DatabasePoolConfig timeout field validates positive values
The `timeout` field in `DatabasePoolConfig` SHALL reject zero and negative values with a `ValidationError`.

#### Scenario: Zero timeout value is rejected
- **WHEN** `DatabasePoolConfig(timeout=0)` is validated
- **THEN** a `ValidationError` SHALL be raised containing the field name `timeout` and a message indicating the value must be greater than 0

#### Scenario: Negative timeout value is rejected
- **WHEN** `DatabasePoolConfig(timeout=-1)` is validated
- **THEN** a `ValidationError` SHALL be raised containing the field name `timeout`

#### Scenario: Positive timeout value is accepted
- **WHEN** `DatabasePoolConfig(timeout=30.0)` is validated
- **THEN** no `ValidationError` SHALL be raised
