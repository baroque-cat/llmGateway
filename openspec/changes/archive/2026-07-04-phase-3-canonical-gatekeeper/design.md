## Context

After Phase 1 (async event loop fix, timeout, markers, .env chain) and Phase 2 (process-isolation Makefile, --run-postgres hook, batching rename), the llmGateway test infrastructure is stable but has two architectural gaps:

1. **No single source of truth for test configuration.** `tests/conftest.py` uses `os.environ.setdefault()` with 17 hardcoded defaults. The same `_BASE_ENV` dictionary (10+ variables) is copy-pasted across 10+ test files in `tests/unit/config/`. Individual tests use `patch.dict(os.environ, ...)` without any canonical reference point. There is no way to verify that test configuration values match `.env.example` and `config/example_full_config.yaml`.

2. **No enforcement against hardcoded test values.** Production URLs, obsolete model names, wrong provider types, hardcoded secrets, and non-canonical configuration values can leak into tests without detection. Copium's gatekeeper — `check-test-hardcodes.sh` with banned-pattern arrays, boundary whitelist algorithm, cache fixtures, and structural tests — prevents this class of problem.

Copium's 6-layer test paradigm provides the blueprint:
- Layer 1 (process isolation): Already copied in Phase 2
- Layer 2 (per-test timeout + markers): Already in pyproject.toml
- Layer 3 (**CanonicalConfig**): Single source of truth — this phase
- Layer 4 (**Gatekeeper**): `check-test-hardcodes.sh` + cache fixtures — this phase
- Layers 5-6 (pre-commit + CI split): Deferred to Phase 4

The main adaptation challenge: **copium is a dual-package monorepo** (simlece + tgcopiumapp, two `_canonical.py` files, cross-package architectural boundaries). **llmGateway is a single-package project** — one `_canonical.py`, no cross-package constraints, simpler directory structure.

## Goals / Non-Goals

**Goals:**
- Create `tests/_canonical.py` with `CanonicalConfig` frozen dataclass (~50 fields) that parses `.env.example` + `config/example_full_config.yaml` deterministically at import time via `ruamel.yaml`
- Replace `os.environ.setdefault()` in `tests/conftest.py` with `canonical_config` session fixture + `_set_config_vars_from_canonical` autouse fixture using `monkeypatch.setenv`
- Add gatekeeper fixtures to `tests/conftest.py`: `CheckerResult` namedtuple, `_cached_checker_results`, `checker_result` accessor, `_cleanup_stale_temp_files`, `_compute_checker_hash`
- Create `scripts/check-test-hardcodes.sh` with 4 modes (canonical/boundary/root/all), 7 banned-pattern arrays, boundary whitelist algorithm
- Create 10+ structural gatekeeper tests at `tests/` root, auto-discovered by Makefile G5 inversion pattern
- Replace duplicated `_BASE_ENV` dicts in `tests/unit/config/` with `CanonicalConfig.from_example_files()`
- Create `TESTING*.md` documentation (4 files adapted from copium)
- Update `tests/AGENTS.md` with current directory tree, markers, and CanonicalConfig section

**Non-Goals:**
- No `.pre-commit-config.yaml` (Phase 4)
- No CI pipeline split (Phase 4)
- No synthetic checker tests (`test_hardcode_checker_core.py`, `test_boundary_compliance.py`, `test_conftest_checker_cache.py`) — Phase 4
- No `docker-compose.yml` test database service
- No `run-postgres-tests.sh`
- No test data changes — existing tests must continue to pass
- No production code changes

## Decisions

### D1: Single `_canonical.py` for the entire project

**Rationale:** llmGateway is a single-package project — all source code lives under `src/`, all tests under `tests/`. Unlike copium (dual-package: simlece + tgcopiumapp), there is no architectural boundary that requires separate `_canonical.py` files. A single `tests/_canonical.py` with ~50 fields covers all test configuration needs.

**Alternatives considered:**
- *Two `_canonical.py` files (like copium)*: Unnecessary overhead for single-package project. No cross-package import restrictions to enforce.
- *No `_canonical.py` — keep `setdefault`*: Leaves the implicit fallback problem unsolved. No canonical reference for gatekeeper checks.

### D2: Four-mode checker script (canonical/boundary/root/all)

**Rationale:** Copium's 4-mode architecture maps naturally to llmGateway's test directory structure:

| Mode | Directories | Strictness | Annotation |
|------|------------|------------|------------|
| `canonical` | `tests/unit/` | STRICT | No `# boundary:` allowed |
| `boundary` | `tests/integration/`, `tests/security/`, `tests/e2e/`, `tests/stress/` | WHITELIST | `# boundary:` annotates exceptions |
| `root` | `tests/` (root-level only, excluding subdirs) | STRICT | No `# boundary:` allowed |
| `all` | All above | Composite | — |

- `tests/unit/` is canonical: unit tests represent pure logic, no real configuration edge cases.
- `tests/integration/`, `tests/security/`, `tests/e2e/` are boundary: may test edge cases that require non-canonical values with documented exceptions.
- `tests/stress/` is boundary: real HTTP/2 servers may use non-canonical timeouts/ports.
- `tests/` root-level is canoncal: gatekeeper infrastructure tests should not contain hardcodes.

**Alternatives considered:**
- *Single `all` mode only*: Loses the distinction between strict (unit) and whitelist (boundary) enforcement. Boundary tests legitimately need non-canonical values for edge cases — the `# boundary:` annotation provides documentation and auditability.
- *Per-file marking instead of per-directory*: More granular but significantly more complex. Directory-based modes match copium's proven pattern.

### D3: Three-layer cache fixture chain

**Rationale:** Copium's cache architecture (3 subprocess calls total, regardless of test count) is the key to performance:

```
Layer 1: _cached_checker_results (session scope)
    Runs check-test-hardcodes.sh once per mode (canonical, boundary, root).
    3 subprocess calls total. Returns MappingProxyType.

Layer 2: checker_result (function scope accessor)
    Returns cached results per-mode. Composes "all" from three cached modes.
    No additional subprocess calls.

Layer 3: _compute_checker_hash (standalone helper)
    Computes sha256 of script + all scanned files.
    Currently standalone (not wired to cache) — session scope is sufficient for CI.
```

**Why not wire `_compute_checker_hash` to the cache:** Session scope already provides fresh results per CI run (each CI job is a new pytest process). Hash-based cross-session invalidation would enable persistent local caches but adds complexity without immediate benefit. Copium made the same decision.

**Alternatives considered:**
- *No cache — direct subprocess per test*: 140+ subprocess calls → 3. 97% reduction in copium's case. Same proportionality applies.
- *Hash-triggered cache invalidation*: More complex, deferred until local dev performance becomes a bottleneck.

### D4: Boundary whitelist via `# boundary:` annotations with 20-line lookback

**Rationale:** Exact copy of copium's `check_boundary_annotations_fixed()` algorithm:
1. Same-line check: `# boundary:` on the same line → PASS
2. Lookback: up to 20 preceding non-blank lines for a `# boundary:` annotation
3. Case-insensitive: `# boundary:` and `# Boundary:` both work
4. One annotation covers multiple subsequent values

This allows boundary tests to use non-canonical values with clear documentation:
```python
# boundary: test with no API key — mock path
api_key=None,  # boundary: no API key in test environment
```

**Alternatives considered:**
- *Per-pattern annotation*: Requires matching annotation text to banned pattern — fragile and verbose.
- *No whitelist — all modes strict*: Forces boundary tests to use canonical values, losing the ability to test edge cases.

### D5: Gatekeeper tests live at `tests/` root, auto-discovered by G5 inversion

**Rationale:** Makefile G5 already implements the inversion pattern: `pytest tests/ --ignore=tests/unit --ignore=tests/integration ...`. Adding gatekeeper test files to `tests/` root requires ZERO Makefile changes. The G5 `-` prefix ensures fault tolerance (0 tests → no error).

**Alternatives considered:**
- *Dedicated `tests/gatekeeper/` directory*: Would require a new G7 group in the Makefile and a new `--ignore` flag. Adds complexity for no benefit.
- *Gatekeeper tests in `tests/unit/`*: Would be collected by G1, mixing structural checks with unit tests. Wrong isolation profile.

### D6: CanonicalConfig replaces, does not coexist with, setdefault

**Rationale:** The `canonical_config` session fixture + `_set_config_vars_from_canonical` autouse fixture provides the same guarantee as `setdefault` (env vars set before every test) with additional benefits:
- Single source of truth (not duplicated `_defaults` dict)
- Immutable (frozen dataclass — cannot be accidentally mutated by tests)
- Testable (fixture behavior can be verified by `test_canonical_fixtures.py`)
- Gatekeeper-compatible (checker script can compare against canonical values)

The migration path:
1. Add `canonical_config` + `_set_config_vars_from_canonical` fixtures
2. Remove `_setup_default_env_vars()` and module-level call
3. Run full test suite — any test that was relying on `setdefault` behavior will get the same values via `monkeypatch.setenv`

**Why `monkeypatch.setenv` over `os.environ.setdefault`:** `monkeypatch` is pytest-native, provides isolation (changes are reverted after each test), and is the pattern used by copium. `setdefault` operates at the `os.environ` level and can leak between tests.

## Risks / Trade-offs

| Risk | Probability | Mitigation |
|------|------------|------------|
| `CanonicalConfig.from_example_files()` fails to parse YAML with `${VAR}` placeholders correctly | Medium | Use `ruamel.yaml` (same library copium uses). Write `test_canonical_config.py` to verify all fields match expected values. The `${VAR}` resolution regex (`_ENV_VAR_RE`) is adapted from copium's verified implementation. |
| Replacing `setdefault` with `monkeypatch.setenv` breaks existing tests | Medium | The autouse fixture `_set_config_vars_from_canonical` runs BEFORE every test, providing the same values. Tests that need different values already use `monkeypatch.setenv` or `patch.dict` — those override the autouse fixture. Run full test suite after migration to verify. |
| Gatekeeper script produces false positives on clean codebase | High | Start with `EXCLUDE_FILES` containing all infrastructure files (conftest.py, _canonical.py, _constants.py, all gatekeeper test files). Run in dry-run mode iteratively. Add exclusions as needed. Copium's experience: false positives are inevitable in first pass, resolved by targeted EXCLUDE_FILES additions. |
| `_cached_checker_results` fails because checker script doesn't exist yet | None | Script is created EARLIER in the same phase. If script is missing, fixture raises `FileNotFoundError` — clear error message, easy to fix. |
| G5 collects 0 tests before gatekeeper tests are written | None | G5 has `-` prefix (fault-tolerant). pytest exit code 5 (no tests) is swallowed by Make. |
| `ruamel.yaml` not in project dependencies | Low | Add to dev dependencies in `pyproject.toml` (`poetry add --group dev ruamel.yaml`). |
| Boundary annotation lookback misses annotations across large comment blocks | Low | The 20 non-blank-line lookback is generous. Copium has validated this across 31 boundary files. |
| Gatekeeper script is bash — not portable to Windows | Low | Windows developers already use WSL or Docker (per `design.md` Phase 2). |
