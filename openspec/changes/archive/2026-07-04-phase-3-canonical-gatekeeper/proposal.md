## Why

After Phase 1 (async fixes + env chain) and Phase 2 (process-isolation Makefile + rename), the test infrastructure is stable but incomplete. Test configuration relies on `os.environ.setdefault()` — an implicit fallback with no single source of truth. The same `_BASE_ENV` dictionary is copy-pasted across 10+ config test files. There is no enforcement preventing hardcoded configuration values, production URLs, or obsolete model names from leaking into tests. Copium's mature gatekeeper paradigm (CanonicalConfig frozen dataclass + `check-test-hardcodes.sh` + cache fixtures + structural tests) provides a proven solution, but needs adaptation for llmGateway's single-package architecture.

## What Changes

- **`tests/_constants.py`** (NEW): Shared mock tokens, replacing duplicated values
- **`tests/_canonical.py`** (NEW, ~460 lines): `CanonicalConfig` frozen dataclass — single source of truth for all test configuration values, parsed from `.env.example` + `config/example_full_config.yaml` at import time via `ruamel.yaml`
- **`tests/conftest.py`** (MODIFIED): Replace `_setup_default_env_vars()` + `os.environ.setdefault()` with `canonical_config` session fixture + `_set_config_vars_from_canonical` autouse fixture. Add gatekeeper fixtures: `CheckerResult` namedtuple, `_cached_checker_results` (session-scoped, runs checker script once per mode), `checker_result` accessor, `_cleanup_stale_temp_files`, `_compute_checker_hash`
- **`scripts/check-test-hardcodes.sh`** (NEW, ~466 lines): Bash gatekeeper script with 4 modes (canonical/boundary/root/all), 7 banned-pattern arrays adapted for llmGateway from `problem_tests.md` §4, boundary whitelist lookback algorithm (20 non-blank lines)
- **13 structural gatekeeper tests** (NEW, `tests/` root-level): `test_canonical_config.py`, `test_canonical_fixtures.py`, `test_constants.py`, `test_hardcode_checker_modes.py`, `test_hardcode_checker_patterns.py`, `test_checker_cache_fixtures.py`, `test_project_structure.py`, `test_makefile_groups.py`, `test_canonical_integrity.py`, `test_secret_isolation.py`, `test_env_example.py`, `test_documentation_sync.py`, `test_testing_docs.py`
- **`_BASE_ENV` deduplication** (MODIFIED, ~10 files in `tests/unit/config/`): Replace copy-pasted dicts with `from tests._canonical import CanonicalConfig`
- **`TESTING*.md`** (NEW, 4 files): `TESTING.md`, `TESTING-GUIDE.md`, `TESTING-RUN.md`, `TESTING-GATEKEEPER.md` — adapted from copium
- **`tests/AGENTS.md`** (MODIFIED): Update directory tree, markers, add CanonicalConfig section
- **`Makefile`** (NO CHANGE to G5): G5 inversion pattern auto-discovers gatekeeper tests at `tests/` root

## Capabilities

### New Capabilities
- `canonical-config`: CanonicalConfig frozen dataclass as single source of truth for test configuration, parsed deterministically from `.env.example` + `config/example_full_config.yaml`. Replaces `os.environ.setdefault()` implicit fallback and 10+ duplicated `_BASE_ENV` dictionaries.
- `gatekeeper-hardcode-checker`: Bash script (`check-test-hardcodes.sh`) with 7 banned-pattern arrays (production URLs, hardcoded secrets, non-canonical DB params, wrong provider types, obsolete model names), 4 execution modes (canonical/boundary/root/all), boundary whitelist algorithm with `# boundary:` annotations, cached checker fixtures in pytest, and 13 structural gatekeeper tests enforcing zero-hardcoded-values policy.

### Modified Capabilities
<!-- No existing spec-level behavior changes. G5 in makefile-test-runner already specifies root-level collection; Phase 3 just populates root-level with actual test files. -->

## Impact

- **`tests/_canonical.py`** — new file, ~460 lines. Imports: `dataclasses`, `pathlib`, `ruamel.yaml`. Reads `.env.example` and `config/example_full_config.yaml`.
- **`tests/_constants.py`** — new file, ~15 lines. No imports.
- **`tests/conftest.py`** — grows from 73 to ~250 lines. Adds imports: `pytest`, `subprocess`, `hashlib`, `types`, `collections.namedtuple`, `pathlib.Path`, `tests._canonical.CanonicalConfig`.
- **`scripts/check-test-hardcodes.sh`** — new file, ~466 lines. Pure bash, no dependencies.
- **13 gatekeeper test files** — new, ~2000 lines total. Root-level in `tests/`.
- **`tests/unit/config/*.py`** — 10+ files modified to use `CanonicalConfig` instead of `_BASE_ENV` dicts.
- **`TESTING*.md`** — 4 new documentation files, ~900 lines total.
- **`tests/AGENTS.md`** — update directory tree, markers, add CanonicalConfig section.
- No production code, no database schema, no API changes. Pure test infrastructure.
