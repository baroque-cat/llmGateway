# Testing Guide — Writing Tests

> How to write tests that comply with the zero-hardcodes policy.

## The Golden Rule

**All configuration values in tests must derive from `CanonicalConfig`.**

No exceptions. No hardcoded DB credentials, provider tokens, API URLs, gateway
ports, or model names. If a test needs a configuration value, it gets it from
`CanonicalConfig.from_example_files()`.

### Why?

- **Single source of truth**: `.env.example` and `config/example_full_config.yaml`
  are the canonical config. Tests should use the same values, not invent their own.
- **No secret leakage**: Production placeholders (`your_secure_password_here`) and
  real API keys must never appear in test files.
- **Maintainability**: When a config value changes in `.env.example`, all tests
  automatically pick up the new value — no find-and-replace across 50 files.

## CanonicalConfig

### What it is

`CanonicalConfig` is a frozen dataclass at `tests/_canonical.py` that parses
`.env.example` and `config/example_full_config.yaml` deterministically. It has
~50 typed fields covering every configuration section.

### How to use it

```python
from tests._canonical import CanonicalConfig

# Get the singleton instance
cfg = CanonicalConfig.from_example_files()

# Access typed fields
assert cfg.db_host == "localhost"
assert cfg.db_port == 5432
assert cfg.gateway_port == 55300
assert cfg.canonical_provider_types == ("anthropic", "openai_like", "gemini")

# Get all 17 env vars as a dict (for patch.dict)
env = cfg.to_env_dict()
with patch.dict(os.environ, env):
    ...
```

### Test-safe overrides

`.env.example` contains production placeholder values (e.g.
`DB_PASSWORD=your_secure_password_here`, empty provider tokens). CanonicalConfig
parses the file for **structure** (keys + non-sensitive values) but overrides
sensitive fields with test-safe mock values from `tests/_constants.py`:

| Env Var | .env.example value | CanonicalConfig value |
| --- | --- | --- |
| `DB_USER` | `llm_gateway` | `test_user` |
| `DB_PASSWORD` | `your_secure_password_here` | `test_password` |
| `DB_NAME` | `llmgateway` | `test_db` |
| `GEMINI_PROD_TOKEN` | (empty) | `test_gemini_token` |
| `ANTHROPIC_TOKEN` | (empty) | `test_anthropic_token` |
| ... | ... | ... |

### The autouse fixture

`tests/conftest.py` provides an autouse fixture `_set_config_vars_from_canonical`
that calls `monkeypatch.setenv` for all 17 env vars before every test. You do
**not** need to set env vars manually — they are already set.

If your test needs different values, override with your own `monkeypatch.setenv`
or `patch.dict(os.environ, ...)`.

## Test Categories

| Category | Directory | Group | Description |
| --- | --- | --- | --- |
| Unit | `tests/unit/` (excl. config) | G1 | Individual functions/classes in isolation |
| Unit (config) | `tests/unit/config/` | G2 | Pydantic schema + config loader tests |
| Integration | `tests/integration/` | G3 | Multi-component interaction |
| Security | `tests/security/` | G3 | Auth, credential sanitization |
| E2E | `tests/e2e/` | G3 | Complete system flows |
| Batching | `tests/batching/` | G4 | Adaptive batch controller |
| Stress | `tests/stress/` | G6 | Real HTTP/2, slow |
| Gatekeeper | `tests/test_*.py` | G5 | Structural integrity tests |

## Boundary Annotations

Boundary tests (integration, security, e2e, batching, stress) may need to use
banned patterns for legitimate reasons — e.g. testing URL construction, verifying
error handling for specific model names.

### How to annotate

Place `# boundary: <reason>` on the same line as the banned value, or within 20
non-blank lines above it:

```python
# boundary: testing URL construction for the Gemini API
url = "https://generativelanguage.googleapis.com/v1/models"
```

Or on the same line:

```python
url = "https://api.anthropic.com/v1/messages"  # boundary: testing Anthropic endpoint
```

### Rules

- **Boundary annotations are only valid in boundary mode** (integration, security,
  e2e, batching, stress directories).
- **Canonical mode** (unit tests) does not honor boundary annotations — zero
  hardcodes, no exceptions.
- **Root mode** (root-level tests) does not honor boundary annotations.
- **Production URLs** (`BANNED_PROD_URLS`) are **always banned in all modes**,
  even with a boundary annotation. Use `# boundary:` only for non-URL patterns.

## Anti-Patterns

### 1. Hardcoded _BASE_ENV dict

```python
# ❌ BAD — hardcoded values, duplicated across files
_BASE_ENV = {
    "DB_HOST": "localhost",
    "DB_USER": "test_user",
    "DB_PASSWORD": "test_password",
}
```

```python
# ✅ GOOD — derived from CanonicalConfig
from tests._canonical import CanonicalConfig
_BASE_ENV = CanonicalConfig.from_example_files().to_env_dict()
```

### 2. Direct os.environ manipulation

```python
# ❌ BAD — leaks across tests, not isolated
os.environ["DB_HOST"] = "localhost"
```

```python
# ✅ GOOD — isolated via monkeypatch or patch.dict
monkeypatch.setenv("DB_HOST", cfg.db_host)
# or
with patch.dict(os.environ, _BASE_ENV):
    ...
```

### 3. Hardcoded model names

```python
# ❌ BAD — "gpt-4" is a banned model name
def test_model_selection():
    model = "gpt-4"
    ...
```

```python
# ✅ GOOD — use canonical model names
def test_model_selection():
    model = cfg.canonical_model_names[0]
    ...
```

### 4. Hardcoded provider types

```python
# ❌ BAD — "openai" is banned (must be "openai_like")
provider_type = "openai"
```

```python
# ✅ GOOD — use canonical provider types
provider_type = cfg.canonical_provider_types[1]  # "openai_like"
```

## Compliance Checklist

Before committing test code, verify:

- [ ] No hardcoded DB credentials (`test_user`, `test_password`, `test_db` are OK
      only inside `_canonical.py` and `_constants.py`)
- [ ] No hardcoded provider tokens — use `tests/_constants.py`
- [ ] No production API URLs in unit tests
- [ ] No banned model names (`gpt-4`, `gpt-3.5-turbo`, `claude-3-opus`, etc.)
- [ ] No banned provider types (`openai`, `deepseek`, `qwen`, `groq`, `claude`, `google`)
- [ ] All env vars come from `CanonicalConfig.to_env_dict()` or the autouse fixture
- [ ] Boundary tests with banned values have `# boundary:` annotations
- [ ] `bash scripts/check-test-hardcodes.sh all` passes with exit code 0
