"""Tests for src/config/__init__.py — load_config and get_config."""

import pytest

from src.config import get_config, load_config
from src.config.schemas import Config

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_config_instance():
    """Reset the global _config_instance before and after each test to avoid
    cross-test contamination of the singleton state."""
    import src.config as config_module

    config_module._config_instance = None
    yield
    config_module._config_instance = None


MINIMAL_YAML = """\
database:
  password: "test_password"

providers:
  test_provider:
    provider_type: "openai_like"
    enabled: true
    api_base_url: "https://api.test.com/v1"
    access_control:
      gateway_access_token: "test_token123"
"""


@pytest.fixture()
def minimal_config_file(tmp_path):
    """Write a minimal valid YAML config to a temp file and return its path."""
    config_file = tmp_path / "providers.yaml"
    config_file.write_text(MINIMAL_YAML, encoding="utf-8")
    return str(config_file)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_load_config_returns_config(minimal_config_file):
    """load_config with a valid YAML file should return a Config object."""
    config = load_config(minimal_config_file)
    assert isinstance(config, Config)
    # Verify some basic fields are populated
    assert "test_provider" in config.providers
    assert config.providers["test_provider"].enabled is True


def test_get_config_after_load(minimal_config_file):
    """After calling load_config, get_config should return the same Config object."""
    config = load_config(minimal_config_file)
    retrieved = get_config()
    assert retrieved is config  # same object (singleton)


def test_get_config_before_load_raises_runtime_error():
    """Calling get_config() before load_config should raise RuntimeError."""
    with pytest.raises(RuntimeError, match="Configuration not loaded"):
        get_config()


def test_load_config_file_not_found(tmp_path):
    """Loading a nonexistent file should raise FileNotFoundError."""
    nonexistent_path = str(tmp_path / "does_not_exist.yaml")
    with pytest.raises(FileNotFoundError, match="not found"):
        load_config(nonexistent_path)
