# metrics-no-model-label

## Purpose

Remove the `model` dimension from the `llm_gateway_keys_total` Prometheus metric. The metric
SHALL show only `provider` and `status` labels, reflecting the architecture where every key has
a single status per provider instance (no per-model distinction).

## ADDED Requirements

### Requirement: llm_gateway_keys_total has no model label
The `llm_gateway_keys_total` Prometheus gauge SHALL define labels `["provider", "status"]`. It SHALL NOT include a `"model"` label.

#### Scenario: Gauge registered without model label
- **WHEN** the Prometheus metrics collector initializes the `llm_gateway_keys_total` gauge
- **THEN** the label names SHALL be `["provider", "status"]`
- **AND** no `"model"` label SHALL be present

#### Scenario: Metric value set with provider and status only
- **WHEN** the collector updates metrics from `get_status_summary()` data
- **THEN** each gauge value SHALL be set with `.labels(provider=..., status=...)` only
- **AND** no `model` keyword argument SHALL be passed

### Requirement: __ALL_MODELS__ is not transformed in metrics
The Prometheus collector SHALL NOT transform or inspect the `model_name` value. Since the `model` label is removed, the `__ALL_MODELS__` → `"shared"` transformation is unnecessary.

#### Scenario: No model transformation code
- **WHEN** the Prometheus backend `collect_from_db()` method is inspected
- **THEN** no code SHALL check for `model_name == "__ALL_MODELS__"` 
- **AND** no code SHALL replace `"__ALL_MODELS__"` with `"shared"` in metric labels

### Requirement: StatusSummaryItem has no model field
The `StatusSummaryItem` TypedDict SHALL contain fields `provider`, `status`, and `count`. It SHALL NOT contain a `model` field.

#### Scenario: TypedDict definition excludes model
- **WHEN** the `StatusSummaryItem` TypedDict is inspected
- **THEN** only `provider: str`, `status: str`, and `count: int` fields SHALL be defined
- **AND** no `model: str` field SHALL be present

### Requirement: get_status_summary() does not group by model
The `get_status_summary()` SQL query SHALL group results by `p.name` and `s.status` only. It SHALL NOT include `s.model_name` in the SELECT or GROUP BY clauses.

#### Scenario: SQL query excludes model dimension
- **WHEN** `get_status_summary()` is called
- **THEN** the SELECT clause SHALL be `p.name AS provider, s.status, COUNT(s.key_id) AS count`
- **AND** the GROUP BY clause SHALL be `p.name, s.status`
- **AND** `s.model_name` SHALL NOT appear in the query
