"""Structural test verifying secret isolation prevents leakage (Scenario S20).

Ensures that production placeholder values from ``.env.example`` are overridden
by test-safe mock values in CanonicalConfig, preventing secret leakage into
the test suite.
"""

from pathlib import Path

from tests._canonical import CanonicalConfig
from tests._constants import (
    MOCK_ANTHROPIC_TOKEN,
    MOCK_DEEPSEEK_TOKEN,
    MOCK_DEFAULT_TOKEN,
    MOCK_GEMINI_TOKEN,
    MOCK_METRICS_TOKEN,
    MOCK_QWEN_TOKEN,
)

_REPO_ROOT: Path = Path(__file__).resolve().parent.parent


def test_secret_isolation_prevents_leakage() -> None:
    """Verify production secrets are overridden with test-safe values (S20).

    Checks:
        - ``db_user`` is ``test_user`` (not ``llm_gateway``)
        - ``db_password`` is ``test_password`` (not the placeholder)
        - ``db_name`` is ``test_db`` (not ``llmgateway``)
        - ``to_env_dict()`` does not contain production values
        - ``.env.example`` contains the production values (confirming override)
        - ``.env`` is listed in ``.gitignore`` (prevents accidental commits)
        - Mock tokens from ``_constants.py`` are used (not empty strings)
    """
    cfg = CanonicalConfig.from_example_files()
    env_dict = cfg.to_env_dict()

    # --- DB credentials overridden with test-safe values ---
    assert (
        cfg.db_user == "test_user"
    ), f"db_user should be 'test_user', got {cfg.db_user!r}"
    assert (
        cfg.db_user != "llm_gateway"
    ), "db_user should NOT be production value 'llm_gateway'"

    assert (
        cfg.db_password == "test_password"
    ), f"db_password should be 'test_password', got {cfg.db_password!r}"
    assert (
        cfg.db_password != "your_secure_password_here"
    ), "db_password should NOT be production placeholder"

    assert cfg.db_name == "test_db", f"db_name should be 'test_db', got {cfg.db_name!r}"
    assert (
        cfg.db_name != "llmgateway"
    ), "db_name should NOT be production value 'llmgateway'"

    # --- to_env_dict() does not contain production values ---
    assert env_dict["DB_USER"] != "llm_gateway"
    assert env_dict["DB_PASSWORD"] != "your_secure_password_here"
    assert env_dict["DB_NAME"] != "llmgateway"

    # --- .env.example contains production values (confirming override) ---
    env_example = (_REPO_ROOT / ".env.example").read_text(encoding="utf-8")
    assert (
        "llm_gateway" in env_example
    ), ".env.example should contain production DB_USER value"
    assert (
        "your_secure_password_here" in env_example
    ), ".env.example should contain production DB_PASSWORD placeholder"
    assert (
        "llmgateway" in env_example
    ), ".env.example should contain production DB_NAME value"

    # --- .env is listed in .gitignore (prevents accidental commits) ---
    gitignore = (_REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
    gitignore_lines = gitignore.splitlines()
    assert any(
        line.strip() == ".env" for line in gitignore_lines
    ), ".env must be listed in .gitignore to prevent accidental commits"

    # --- Mock tokens used instead of empty strings ---
    assert (
        cfg.llm_provider_default_token == MOCK_DEFAULT_TOKEN
    ), "llm_provider_default_token should use mock token from _constants"
    assert (
        cfg.gemini_prod_token == MOCK_GEMINI_TOKEN
    ), "gemini_prod_token should use mock token from _constants"
    assert (
        cfg.deepseek_token == MOCK_DEEPSEEK_TOKEN
    ), "deepseek_token should use mock token from _constants"
    assert (
        cfg.anthropic_token == MOCK_ANTHROPIC_TOKEN
    ), "anthropic_token should use mock token from _constants"
    assert (
        cfg.qwen_home_token == MOCK_QWEN_TOKEN
    ), "qwen_home_token should use mock token from _constants"
    assert (
        cfg.metrics_access_token == MOCK_METRICS_TOKEN
    ), "metrics_access_token should use mock token from _constants"

    # --- Tokens are non-empty (unlike .env.example which has empty strings) ---
    token_keys: list[str] = [
        "LLM_PROVIDER_DEFAULT_TOKEN",
        "GEMINI_PROD_TOKEN",
        "DEEPSEEK_TOKEN",
        "ANTHROPIC_TOKEN",
        "QWEN_HOME_TOKEN",
        "METRICS_ACCESS_TOKEN",
    ]
    for key in token_keys:
        assert env_dict[key] != "", f"{key} should be non-empty (mock token)"
