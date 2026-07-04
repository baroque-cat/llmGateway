## ADDED Requirements

### Requirement: Gatekeeper test enforces architectural layer import boundaries

The project SHALL provide a `test_layer_import_scan.py` root-level gatekeeper test that uses AST-based static analysis to verify that Python imports do not violate the project's architectural layering constraints.

#### Scenario: config/ layer does not import from db/ or services/

- **WHEN** all `.py` files under `src/config/` are statically analyzed
- **THEN** no file SHALL contain imports from `src.db` or `src.db.`
- **AND** no file SHALL contain imports from `src.services` or `src.services.`

#### Scenario: db/ layer does not import from providers/ or services/

- **WHEN** all `.py` files under `src/db/` are statically analyzed
- **THEN** no file SHALL contain imports from `src.providers` or `src.providers.`
- **AND** no file SHALL contain imports from `src.services` or `src.services.`

#### Scenario: metrics/ layer does not import from services/ or providers/

- **WHEN** all `.py` files under `src/metrics/` are statically analyzed
- **THEN** no file SHALL contain imports from `src.services` or `src.services.`
- **AND** no file SHALL contain imports from `src.providers` or `src.providers.`

#### Scenario: providers/ layer does not import from services/

- **WHEN** all `.py` files under `src/providers/` are statically analyzed
- **THEN** no file SHALL contain imports from `src.services` or `src.services.`

#### Scenario: core/ layer has no forbidden layer dependencies

- **WHEN** all `.py` files under `src/core/` are statically analyzed
- **THEN** no file SHALL contain imports from `src.config`, `src.db`, `src.metrics`, `src.providers`, or `src.services`
- **AND** allowed imports from `src.core` submodules (self-references) SHALL be permitted

#### Scenario: Well-known exceptions are whitelisted

- **WHEN** a forbidden import is detected but it matches a pre-approved exception
- **THEN** the violation SHALL be suppressed for that specific import
- **AND** the exception SHALL be documented with a comment explaining why it is allowed
