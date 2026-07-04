# Testing Run — Running Tests

> How to run tests, Makefile targets, and process-isolation groups.

## Makefile Targets

| Target | Command | Description | Est. Time |
| --- | --- | --- | --- |
| `make test` | G1–G5 | Everyday development test suite | ~3 s |
| `make test-slow` | G6 | Stress tests (real HTTP/2, `@pytest.mark.slow`) | ~60 s |
| `make test-postgres` | — | Tests requiring live PostgreSQL (`--run-postgres`) | varies |
| `make test-all` | G1–G6 | Full suite including stress | ~65 s |
| `make ci` | lint + typecheck + test | CI pipeline (ruff + pyright + G1–G5) | ~10 s |
| `make lint` | ruff check | Lint src/ and tests/ | ~1 s |
| `make typecheck` | pyright | Type check in strict mode | ~5 s |

## Process-Isolation Groups (G1–G6)

Each group is a **separate `poetry run pytest` invocation** — a fresh Python
process with its own asyncio event loop. This prevents event-loop contamination
between test categories.

### G1: Unit Tests (gate)

```bash
poetry run pytest tests/unit/ --ignore=tests/unit/config -q --timeout=30 -m "not slow and not postgres"
```

- **Scope**: `tests/unit/` excluding `tests/unit/config/`
- **Timeout**: 30 s per test
- **Markers**: excludes `slow` and `postgres`
- **Prefix**: no `-` (gate — failure stops `make test`)
- **Count**: ~880 tests

### G2: Config Tests

```bash
-poetry run pytest tests/unit/config/ -q --timeout=30 -m "not slow and not postgres"
```

- **Scope**: `tests/unit/config/`
- **Timeout**: 30 s per test
- **Markers**: excludes `slow` and `postgres`
- **Prefix**: `-` (fault-tolerant — failure does not stop `make test`)
- **Count**: ~300 tests

### G3: Integration + Security + E2E

```bash
-poetry run pytest tests/integration/ tests/security/ tests/e2e/ -q --timeout=30 -m "not slow and not postgres"
```

- **Scope**: `tests/integration/`, `tests/security/`, `tests/e2e/`
- **Timeout**: 30 s per test
- **Markers**: excludes `slow` and `postgres`
- **Prefix**: `-` (fault-tolerant)
- **Count**: ~150 tests

### G4: Batching Tests

```bash
-poetry run pytest tests/batching/ -q --timeout=30 -m "not slow and not postgres"
```

- **Scope**: `tests/batching/`
- **Timeout**: 30 s per test
- **Markers**: excludes `slow` and `postgres`
- **Prefix**: `-` (fault-tolerant)

### G5: Root-Level Tests (Gatekeeper)

```bash
-poetry run pytest tests/ \
    --ignore=tests/unit \
    --ignore=tests/integration \
    --ignore=tests/security \
    --ignore=tests/e2e \
    --ignore=tests/stress \
    --ignore=tests/batching \
    -q --timeout=30 -m "not slow and not postgres"
```

- **Scope**: `tests/*.py` (root-level only, collected via inversion — ignore all subdirectories)
- **Timeout**: 30 s per test
- **Markers**: excludes `slow` and `postgres`
- **Prefix**: `-` (fault-tolerant)
- **Purpose**: Gatekeeper structural tests (`test_project_structure.py`, `test_canonical_integrity.py`, etc.)

### G6: Stress Tests

```bash
poetry run pytest tests/stress/ -q --timeout=60 -m slow
```

- **Scope**: `tests/stress/`
- **Timeout**: 60 s per test
- **Markers**: **only** `slow` (positive filter)
- **Prefix**: no `-` (gate — only runs via `make test-slow`)
- **Count**: varies

## Timeout Policy

| Group | Timeout | Rationale |
| --- | --- | --- |
| G1–G5 | 30 s | Unit/integration tests should be fast; 30 s is generous |
| G6 | 60 s | Stress tests with real HTTP/2 need more time |

Tests that exceed the timeout are killed by pytest-timeout and reported as `TIMEOUT`.

## Markers

| Marker | Meaning | Default Behavior |
| --- | --- | --- |
| `@pytest.mark.slow` | Stress test, real HTTP/2 | Excluded from G1–G5, only in G6 |
| `@pytest.mark.postgres` | Requires live PostgreSQL | Skipped unless `--run-postgres` |
| `@pytest.mark.meta` | Meta-test (structural) | Runs in G5 |

## Typical Workflow

### Everyday development

```bash
# Run the full suite (G1–G5)
make test

# Run a specific test file
poetry run pytest tests/unit/core/test_constants.py -v

# Run a specific test function
poetry run pytest tests/unit/config/test_loader.py::test_config_loader_load_success -v

# Run with coverage
poetry run pytest tests/unit/ --cov=src
```

### Before pushing

```bash
# Mirror CI
make ci

# Or step by step
make lint
make typecheck
make test
```

### Stress testing

```bash
# Run stress tests only
make test-slow

# Run everything
make test-all
```

### Postgres integration

```bash
# Start PostgreSQL (via Docker)
docker-compose up -d postgres

# Run postgres-marked tests
make test-postgres
```

## Debugging

### Verbose output

```bash
poetry run pytest tests/unit/config/test_loader.py -v -s
```

### Stop on first failure

```bash
poetry run pytest tests/unit/ -x
```

### Show local variables on failure

```bash
poetry run pytest tests/unit/ -x --tb=long
```

### Run with logging

```bash
poetry run pytest tests/unit/ --log-cli-level=DEBUG
```
