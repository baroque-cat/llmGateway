"""Tests for CanonicalConfig — parses .env.example and example_full_config.yaml.

Verifies that ``CanonicalConfig.from_example_files()`` correctly parses the
canonical configuration files and applies test-safe overrides for sensitive
fields (DB credentials, provider tokens).

Scenarios covered:
    S1: Parses example files correctly (field-by-field assertions).
    S4: Import-safe from any test file (frozen dataclass, transitive imports).
"""

from __future__ import annotations

import dataclasses
from typing import Any

from tests._canonical import CanonicalConfig
from tests._constants import (
    MOCK_ANTHROPIC_TOKEN,
    MOCK_DEEPSEEK_TOKEN,
    MOCK_DEFAULT_TOKEN,
    MOCK_GEMINI_TOKEN,
    MOCK_METRICS_TOKEN,
    MOCK_QWEN_TOKEN,
)


def test_parses_example_files_correctly() -> None:
    """S1: CanonicalConfig.from_example_files() parses .env.example and YAML.

    Verifies database, gateway, keeper, metrics, provider tokens, timeout,
    and adaptive batching fields match expected values from the example files.
    Also verifies test-safe overrides are applied for sensitive fields.
    """
    cfg = CanonicalConfig.from_example_files()

    # === Database fields (from .env.example, with test-safe overrides) ===
    assert cfg.db_host == "localhost"
    assert cfg.db_port == 5432
    assert cfg.db_user == "test_user"  # overridden from "llm_gateway"
    assert cfg.db_password == "test_password"  # overridden from placeholder
    assert cfg.db_name == "test_db"  # overridden from "llmgateway"

    # === Database Pool (from YAML) ===
    assert cfg.db_pool_min_size == 1
    assert cfg.db_pool_max_size == 15
    assert cfg.db_pool_command_timeout == 30.0
    assert cfg.db_pool_timeout == 60.0

    # === Database Retry (from YAML) ===
    assert cfg.db_retry_max_attempts == 3
    assert cfg.db_retry_base_delay_sec == 1.0
    assert cfg.db_retry_backoff_factor == 2.0
    assert cfg.db_retry_jitter is True

    # === Database Vacuum (from YAML) ===
    assert cfg.db_vacuum_interval_minutes == 60
    assert cfg.db_vacuum_dead_tuple_ratio_threshold == 0.3

    # === Gateway (from .env.example) ===
    assert cfg.gateway_host == "0.0.0.0"
    assert cfg.gateway_port == 55300
    assert cfg.gateway_workers == 4

    # === Keeper (port from .env.example, concurrency from YAML) ===
    assert cfg.keeper_metrics_port == 9090
    assert cfg.keeper_max_concurrent_providers == 10

    # === HTTP Client (from YAML) ===
    assert cfg.http2_enabled is True
    assert cfg.pool_max_connections == 200
    assert cfg.pool_max_keepalive == 50
    assert cfg.pool_keepalive_expiry == 30.0

    # === Timeouts (from YAML, first provider with timeouts) ===
    assert cfg.timeout_connect == 10.0
    assert cfg.timeout_read == 120.0
    assert cfg.timeout_write == 20.0
    assert cfg.timeout_pool == 15.0
    assert cfg.timeout_total == 600.0
    assert cfg.timeout_stream_read is None

    # === Metrics (from YAML + .env.example) ===
    assert cfg.metrics_enabled is True
    assert cfg.metrics_access_token == MOCK_METRICS_TOKEN  # overridden
    assert cfg.metrics_backend == ""
    assert cfg.prometheus_multiproc_dir == ""

    # === Provider tokens (from .env.example, with test-safe overrides) ===
    assert cfg.llm_provider_default_token == MOCK_DEFAULT_TOKEN
    assert cfg.gemini_prod_token == MOCK_GEMINI_TOKEN
    assert cfg.deepseek_token == MOCK_DEEPSEEK_TOKEN
    assert cfg.anthropic_token == MOCK_ANTHROPIC_TOKEN
    assert cfg.qwen_home_token == MOCK_QWEN_TOKEN

    # === Adaptive Batching (from YAML, first provider) ===
    assert cfg.adaptive_start_batch_size == 10
    assert cfg.adaptive_start_batch_delay_sec == 30.0
    assert cfg.adaptive_min_batch_size == 5
    assert cfg.adaptive_max_batch_size == 50
    assert cfg.adaptive_min_batch_delay_sec == 3.0
    assert cfg.adaptive_max_batch_delay_sec == 120.0

    # === Health Policy (from YAML, first provider) ===
    assert cfg.task_timeout_sec == 900
    assert cfg.verification_attempts == 3
    assert cfg.verification_delay_sec == 65
    assert cfg.purge_after_days == 180

    # === Canonical lists ===
    assert "anthropic" in cfg.canonical_provider_types
    assert "openai_like" in cfg.canonical_provider_types
    assert "gemini" in cfg.canonical_provider_types
    assert "gemini-2.5-flash" in cfg.canonical_model_names
    assert "deepseek-chat" in cfg.canonical_model_names


def test_import_safe_from_any_test_file() -> None:
    """S4: CanonicalConfig and constants are import-safe from any test file.

    Verifies that importing ``tests._canonical`` and ``tests._constants``
    succeeds (transitively imports ``ruamel.yaml``), that CanonicalConfig is
    a frozen dataclass, and that ``from_example_files()`` returns a
    CanonicalConfig instance.
    """
    # Module-level imports at the top of this file already prove import-safety.
    # Verify CanonicalConfig is a dataclass.
    assert dataclasses.is_dataclass(CanonicalConfig)

    # Verify CanonicalConfig is frozen.  __dataclass_params__ is a private
    # CPython attribute that pyright does not model, so we use getattr.
    params: Any = getattr(CanonicalConfig, "__dataclass_params__", None)
    assert params is not None
    assert bool(params.frozen) is True

    # Verify from_example_files() returns a CanonicalConfig instance.
    cfg = CanonicalConfig.from_example_files()
    assert isinstance(cfg, CanonicalConfig)
