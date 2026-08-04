# provider-key-pool — Delta Spec

## MODIFIED Requirements

### Requirement: get_key_from_pool accepts provider_name only
`get_key_from_pool()` SHALL accept a single `provider_name` argument and SHALL NOT accept a `model_name` argument. The selection strategy SHALL depend on the provider's configured key selection mode. In `round_robin` mode (default), it SHALL return any available key from the provider's pool using round-robin rotation, exactly as before the `sticky-key-selection` capability was introduced. In `sticky` mode, it SHALL return keys according to the `sticky-key-selection` capability requirements (sticky pointer without deque rotation).

#### Scenario: Key retrieved without model name in round-robin mode
- **WHEN** `get_key_from_pool("my-provider")` is called and the provider uses `round_robin` mode
- **THEN** the method SHALL return a `(key_id, key_value)` tuple from the pool keyed by `"my-provider"`
- **AND** the key SHALL be rotated to the back of the deque

#### Scenario: Sticky mode returns pointer key without rotation
- **WHEN** `get_key_from_pool("my-provider")` is called and the provider uses `sticky` mode with a valid sticky pointer
- **THEN** the method SHALL return the pointer's `(key_id, key_value)` tuple
- **AND** the deque SHALL NOT be rotated for the selected key

#### Scenario: No valid keys available
- **WHEN** `get_key_from_pool("my-provider")` is called and the pool is empty
- **THEN** the method SHALL return `None`
