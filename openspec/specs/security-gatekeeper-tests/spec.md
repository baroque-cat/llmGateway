# security-gatekeeper-tests

## Purpose

Gatekeeper test (`test_security.py`) that scans the repository for hardcoded
secrets, tokens, and keys in source files, verifies `.gitignore` coverage of
`.env`, and ensures no committed credential files exist.

## Requirements

### Requirement: Gatekeeper test verifies no hardcoded secrets in source code

The project SHALL provide a `test_security.py` root-level gatekeeper test that
scans the repository for hardcoded secrets, tokens, and keys in source files.

#### Scenario: .env is in .gitignore

- **WHEN** the repository root is scanned
- **THEN** `.gitignore` SHALL contain an entry for `.env` (to prevent committing real credentials)

#### Scenario: No hardcoded passwords in source files

- **WHEN** `src/` source files are scanned for password-like patterns
- **THEN** no file SHALL contain strings matching `password="test_secret"` or similar non-canonical passwords
- **AND** files in `EXCLUDE_FILES` from the gatekeeper script SHALL be excluded from this check

#### Scenario: No private key files committed

- **WHEN** the repository is scanned for sensitive file extensions
- **THEN** no files with extensions `.pem`, `.key`, `.crt`, `.p12`, `.pfx` SHALL exist in the repository
- **AND** no files named `id_rsa`, `id_ed25519`, or similar private key names SHALL exist

#### Scenario: No committed .env files except .env.example

- **WHEN** the repository is scanned for `.env` files
- **THEN** the only `.env` file present SHALL be `.env.example`
- **AND** no other files with `.env` in their name SHALL exist (excluding `.env.example`)
