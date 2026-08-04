#!/usr/bin/env python3

"""Tests for CircuitBreakerParams frozen dataclass — construction and immutability."""

import dataclasses

import pytest

from src.core.models import CircuitBreakerParams


def test_circuit_breaker_params_frozen_immutable() -> None:
    """CircuitBreakerParams is a frozen dataclass constructible with 7 fields;
    attribute assignment raises FrozenInstanceError."""
    params = CircuitBreakerParams(
        window_size=20,
        error_rate_threshold=0.5,
        min_samples=5,
        open_duration_sec=30.0,
        backoff_factor=2.0,
        max_open_duration_sec=300.0,
        probe_successes_to_close=3,
    )

    # Verify all 7 fields are accessible with the values passed
    assert params.window_size == 20
    assert params.error_rate_threshold == 0.5
    assert params.min_samples == 5
    assert params.open_duration_sec == 30.0
    assert params.backoff_factor == 2.0
    assert params.max_open_duration_sec == 300.0
    assert params.probe_successes_to_close == 3

    # Verify immutability
    with pytest.raises(dataclasses.FrozenInstanceError):
        params.window_size = 99  # type: ignore[misc]
