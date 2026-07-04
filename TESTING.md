# Testing Documentation

> **Single entry point** for all testing documentation in the llmGateway project.

## Quick Start

```bash
# Run the full test suite (G1–G5, ~3 s)
make test

# Run stress tests (G6, slow)
make test-slow

# Run everything including stress
make test-all

# Run with a live PostgreSQL instance
make test-postgres

# CI pipeline: lint + typecheck + test
make ci
```

## Documentation Index

| Document | Audience | Content |
| --- | --- | --- |
| [TESTING-GUIDE.md](TESTING-GUIDE.md) | Test authors | Golden Rule (zero hardcodes), CanonicalConfig, boundary annotations, anti-patterns, compliance checklist |
| [TESTING-RUN.md](TESTING-RUN.md) | Developers, CI | Makefile targets, process-isolation groups (G1–G6), timeout policy, markers, typical workflow |
| [TESTING-GATEKEEPER.md](TESTING-GATEKEEPER.md) | Maintainers | Script architecture (4 modes), banned-pattern arrays, cache fixtures, test classification, enforcement layers |

## By Role

### I'm writing a test

1. Read [TESTING-GUIDE.md](TESTING-GUIDE.md) — especially the Golden Rule.
2. Use `CanonicalConfig.from_example_files()` for all configuration values.
3. Never hardcode DB credentials, provider tokens, or API URLs.
4. If a boundary test *must* use a banned value, annotate with `# boundary: <reason>`.
5. Run `bash scripts/check-test-hardcodes.sh all` before committing.

### I'm running tests

1. Read [TESTING-RUN.md](TESTING-RUN.md) for Makefile targets and group details.
2. Use `make test` for everyday development (G1–G5, ~3 s).
3. Use `make test-slow` for stress tests (G6).
4. Use `make ci` to mirror the CI pipeline.

### I'm maintaining the gatekeeper

1. Read [TESTING-GATEKEEPER.md](TESTING-GATEKEEPER.md) for the full architecture.
2. The script lives at `scripts/check-test-hardcodes.sh`.
3. Cache fixtures are in `tests/conftest.py`.
4. Structural tests are at `tests/test_*.py` (root level).

## Test Directory Structure

```
tests/
├── _canonical.py          # CanonicalConfig — single source of truth
├── _constants.py          # Shared mock token constants
├── conftest.py            # Global fixtures (env setup, gatekeeper cache)
├── test_*.py              # Root-level gatekeeper tests (G5)
├── unit/                  # Unit tests (G1 + G2)
│   ├── config/            # Config schema/loader tests (G2)
│   ├── core/              # Domain logic tests (G1)
│   ├── db/                # Database layer tests (G1)
│   ├── metrics/           # Metrics tests (G1)
│   ├── providers/         # Provider adapter tests (G1)
│   └── services/          # Service layer tests (G1)
├── integration/           # Integration tests (G3)
├── security/              # Security tests (G3)
├── e2e/                   # End-to-end tests (G3)
├── batching/              # Adaptive batching tests (G4)
└── stress/                # Stress tests (G6, @pytest.mark.slow)
```
