# config-default-model-dict

## Purpose

Defines the configuration structure for LLM provider model definitions, replacing the
separate `default_model: str` and `models: dict[str, ModelInfo]` fields with a single
`default_model: dict[str, ModelInfo]` field used exclusively by the Keeper for
health-check model resolution. The gateway ignores this field entirely in transparent
proxy mode.

## Requirements

### Requirement: default_model is a dict of ModelInfo
`ProviderConfig.default_model` SHALL be a `dict[str, ModelInfo]` field, mapping model names to their configuration (endpoint_suffix, test_payload). It SHALL default to an empty dict.

#### Scenario: Single model in default_model
- **WHEN** the YAML config contains:
  ```yaml
  default_model:
    gemini-2.5-flash:
      endpoint_suffix: ":generateContent"
      test_payload:
        contents:
          - parts:
              - text: "Hello"
  ```
- **THEN** `provider_config.default_model` SHALL be `{"gemini-2.5-flash": ModelInfo(endpoint_suffix=":generateContent", test_payload={...})}`

#### Scenario: Empty default_model is valid
- **WHEN** the YAML config contains no `default_model` section
- **THEN** `provider_config.default_model` SHALL be an empty dict `{}`

### Requirement: models field is removed from ProviderConfig
`ProviderConfig` SHALL NOT have a `models` field. The `ModelInfo` dictionary SHALL be accessible only through `default_model`.

#### Scenario: Config validation rejects models field
- **WHEN** the YAML config contains a `models:` section
- **THEN** Pydantic validation SHALL reject the config with an `extra_forbid` error

### Requirement: ConfigAccessor get_model_info uses default_model
`ConfigAccessor.get_model_info(provider_name, model_name)` SHALL look up the model in `provider.default_model` instead of a removed `provider.models` dict.

#### Scenario: Model info retrieved from default_model
- **WHEN** `accessor.get_model_info("my-provider", "gpt-4")` is called
- **THEN** the method SHALL return `provider.default_model.get("gpt-4")` or `None`

### Requirement: ConfigAccessor get_default_model_info returns first ModelInfo
`ConfigAccessor.get_default_model_info(provider_name)` SHALL return the first `ModelInfo` value from `provider.default_model`, or `None` if the dict is empty.

#### Scenario: Default model info returned
- **WHEN** `accessor.get_default_model_info("my-provider")` is called and `default_model` contains `{"gpt-4": ModelInfo(...), "gpt-3.5": ModelInfo(...)}`
- **THEN** the method SHALL return the `ModelInfo` for `"gpt-4"` (first key in iteration order)

#### Scenario: Empty default_model returns None
- **WHEN** `accessor.get_default_model_info("my-provider")` is called and `default_model` is empty
- **THEN** the method SHALL return `None`

### Requirement: Keeper uses default_model as its model list
The Keeper's `run_sync_cycle()` SHALL extract model names from `provider_config.default_model.keys()` for `key_model_status` synchronization.

#### Scenario: Models extracted from default_model for sync
- **WHEN** the Keeper processes a provider with `default_model: {gpt-4: ..., gpt-3.5: ...}`
- **THEN** `models_from_config` SHALL be `["gpt-4", "gpt-3.5"]`

### Requirement: KeyProbe resolves model from default_model dict
When a health check uses `ALL_MODELS_MARKER` (shared-key provider), `_check_resource()` SHALL resolve the actual model name from `provider_config.default_model` by taking the first key.

#### Scenario: Shared-key check resolved from default_model
- **WHEN** `_check_resource()` receives `model_name = "__ALL_MODELS__"` and `provider_config.default_model` is `{"gemini-2.5-flash": ModelInfo(...)}`
- **THEN** `actual_model_name` SHALL be resolved to `"gemini-2.5-flash"`

#### Scenario: Empty default_model on shared-key check returns BAD_REQUEST
- **WHEN** `_check_resource()` receives `model_name = "__ALL_MODELS__"` and `provider_config.default_model` is empty
- **THEN** the method SHALL return `CheckResult.fail(ErrorReason.BAD_REQUEST, "No model available for shared key check")`

### Requirement: Provider implementations access default_model instead of models
All concrete provider implementations (`OpenAILikeProvider`, `AnthropicProvider`, `GeminiProvider`) SHALL access model configuration via `self.config.default_model` instead of `self.config.models`.

#### Scenario: Health check URL uses default_model
- **WHEN** `OpenAILikeProvider.check()` looks up model info for a given model name
- **THEN** it SHALL call `self.config.default_model.get(model)` instead of `self.config.models.get(model)`

#### Scenario: inspect() returns keys from default_model
- **WHEN** `provider.inspect()` is called on any provider
- **THEN** it SHALL return `list(self.config.default_model.keys())` instead of `list(self.config.models.keys())`
