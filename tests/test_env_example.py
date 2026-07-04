"""Structural test verifying .env.example completeness (Scenario S21).

Ensures that ``.env.example`` defines exactly 17 environment variables,
all of which are present in ``CanonicalConfig.to_env_dict()``.
"""

from pathlib import Path

from tests._canonical import CanonicalConfig

_REPO_ROOT: Path = Path(__file__).resolve().parent.parent

# Required env var names that must be present in .env.example
_REQUIRED_ENV_VARS: list[str] = [
    "DB_HOST",
    "DB_PORT",
    "DB_USER",
    "DB_PASSWORD",
    "DB_NAME",
    "GATEWAY_HOST",
    "GATEWAY_PORT",
    "GATEWAY_WORKERS",
    "KEEPER_METRICS_PORT",
    "METRICS_ACCESS_TOKEN",
    "METRICS_BACKEND",
    "PROMETHEUS_MULTIPROC_DIR",
    "LLM_PROVIDER_DEFAULT_TOKEN",
    "GEMINI_PROD_TOKEN",
    "DEEPSEEK_TOKEN",
    "ANTHROPIC_TOKEN",
    "QWEN_HOME_TOKEN",
]


def _parse_env_example(content: str) -> dict[str, str]:
    """Parse .env.example content into a dict of key-value pairs.

    Skips comment lines and blank lines.  Strips inline comments.

    Args:
        content: Raw text content of ``.env.example``.

    Returns:
        Mapping of env var name to its value (may be empty string).
    """
    result: dict[str, str] = {}
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        if "#" in value:
            value = value.split("#", 1)[0]
        result[key.strip()] = value.strip()
    return result


def test_env_example_validates_completeness() -> None:
    """Verify .env.example has 17 vars, all in CanonicalConfig (S21).

    Checks:
        - Exactly 17 environment variable definitions
        - All 17 vars are in ``CanonicalConfig.to_env_dict()``
        - Required vars (DB_HOST, DB_PORT, etc.) are present
        - Each var line has ``=`` (key-value format, not bare key)
    """
    env_example_path = _REPO_ROOT / ".env.example"
    assert env_example_path.is_file(), "Missing .env.example at repo root"

    content = env_example_path.read_text(encoding="utf-8")

    # --- Each non-comment, non-blank line has '=' (format check) ---
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        assert "=" in line, f"Env var line without '=': {line!r}"

    # --- Parse and count ---
    parsed = _parse_env_example(content)
    assert (
        len(parsed) == 17
    ), f".env.example should define 17 env vars, got {len(parsed)}"

    # --- All parsed vars are in to_env_dict() ---
    env_dict = CanonicalConfig.from_example_files().to_env_dict()
    for key in parsed:
        assert (
            key in env_dict
        ), f"Env var {key!r} from .env.example not in to_env_dict()"

    # --- Required vars present ---
    for var_name in _REQUIRED_ENV_VARS:
        assert (
            var_name in parsed
        ), f"Required env var {var_name!r} not found in .env.example"
