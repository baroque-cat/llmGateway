#!/usr/bin/env python3

"""Tests for metric name registry — UT-REG01 through UT-REG03.

Verifies that metric name constants match expected values and
that ``METRIC_DESCRIPTIONS`` covers every registered name.
"""

from src.metrics.registry import (
    ADAPTIVE_BACKOFF_EVENTS,
    ADAPTIVE_BATCH_DELAY,
    ADAPTIVE_BATCH_SIZE,
    ADAPTIVE_RATE_LIMIT_EVENTS,
    ADAPTIVE_RECOVERY_EVENTS,
    ALL_METRIC_NAMES,
    DB_DEAD_RATIO,
    DB_DEAD_TUPLES,
    DB_PURGED_KEYS,
    DB_VACUUM_COUNT,
    KEY_STATUS_TOTAL,
    METRIC_DESCRIPTIONS,
)


# ---------------------------------------------------------------------------
# UT-REG01 — KEY_STATUS_TOTAL == "llm_gateway_keys_total"
# ---------------------------------------------------------------------------


def test_key_status_total_constant() -> None:
    """UT-REG01: KEY_STATUS_TOTAL is identical to the current name."""
    assert KEY_STATUS_TOTAL == "llm_gateway_keys_total"


# ---------------------------------------------------------------------------
# UT-REG02 — All 10 metric constants match expected names
# ---------------------------------------------------------------------------


def test_all_metric_constants_match_expected_names() -> None:
    """UT-REG02: All metric name constants match their expected string values."""
    expected: dict[str, str] = {
        "KEY_STATUS_TOTAL": "llm_gateway_keys_total",
        "ADAPTIVE_BATCH_SIZE": "llm_gateway_adaptive_batch_size",
        "ADAPTIVE_BATCH_DELAY": "llm_gateway_adaptive_batch_delay",
        "ADAPTIVE_RATE_LIMIT_EVENTS": "llm_gateway_adaptive_rate_limit_events_total",
        "ADAPTIVE_BACKOFF_EVENTS": "llm_gateway_adaptive_backoff_events_total",
        "ADAPTIVE_RECOVERY_EVENTS": "llm_gateway_adaptive_recovery_events_total",
        "DB_DEAD_TUPLES": "llm_gateway_db_dead_tuples",
        "DB_DEAD_RATIO": "llm_gateway_db_dead_ratio",
        "DB_VACUUM_COUNT": "llm_gateway_db_vacuum_count",
        "DB_PURGED_KEYS": "llm_gateway_purged_keys_total",
    }

    actual: dict[str, str] = {
        "KEY_STATUS_TOTAL": KEY_STATUS_TOTAL,
        "ADAPTIVE_BATCH_SIZE": ADAPTIVE_BATCH_SIZE,
        "ADAPTIVE_BATCH_DELAY": ADAPTIVE_BATCH_DELAY,
        "ADAPTIVE_RATE_LIMIT_EVENTS": ADAPTIVE_RATE_LIMIT_EVENTS,
        "ADAPTIVE_BACKOFF_EVENTS": ADAPTIVE_BACKOFF_EVENTS,
        "ADAPTIVE_RECOVERY_EVENTS": ADAPTIVE_RECOVERY_EVENTS,
        "DB_DEAD_TUPLES": DB_DEAD_TUPLES,
        "DB_DEAD_RATIO": DB_DEAD_RATIO,
        "DB_VACUUM_COUNT": DB_VACUUM_COUNT,
        "DB_PURGED_KEYS": DB_PURGED_KEYS,
    }

    assert actual == expected


# ---------------------------------------------------------------------------
# UT-REG03 — METRIC_DESCRIPTIONS contains description for each name
# ---------------------------------------------------------------------------


def test_metric_descriptions_cover_all_names() -> None:
    """UT-REG03: Every name in ALL_METRIC_NAMES has a description in METRIC_DESCRIPTIONS."""
    for name in ALL_METRIC_NAMES:
        assert name in METRIC_DESCRIPTIONS, f"Missing description for metric: {name}"
        # Description must be a non-empty string
        assert isinstance(METRIC_DESCRIPTIONS[name], str)
        assert len(METRIC_DESCRIPTIONS[name]) > 0, f"Empty description for: {name}"