"""Tests for CircuitBreakerConfig schema validation, defaults, and conversion.

Covers spec capability ``gateway-circuit-breaker`` / "Circuit breaker
configuration schema":

  - Defaults are applied when the section is entirely omitted.
  - Inconsistent window settings (min_samples > window_size) are rejected.
  - All Pydantic field-level boundary constraints are validated.
  - ``to_params()`` converts to a pure ``CircuitBreakerParams`` dataclass.
"""

import pytest
from pydantic import ValidationError

from src.config.schemas import CircuitBreakerConfig
from src.core.models import CircuitBreakerParams
from tests._canonical import CanonicalConfig

# Canonical config for deriving expected defaults.
_cfg = CanonicalConfig.from_example_files()


class TestCircuitBreakerDefaults:
    """Defaults applied when the ``circuit_breaker`` section is omitted."""

    def test_defaults_applied_when_section_omitted(self) -> None:
        """All 8 defaults are applied; values derived from ``CanonicalConfig``."""
        cb = CircuitBreakerConfig()

        assert cb.enabled is _cfg.cb_enabled
        assert cb.window_size == _cfg.cb_window_size
        assert cb.error_rate_threshold == _cfg.cb_error_rate_threshold
        assert cb.min_samples == _cfg.cb_min_samples
        assert cb.open_duration_sec == _cfg.cb_open_duration_sec
        assert cb.backoff_factor == _cfg.cb_backoff_factor
        assert cb.max_open_duration_sec == _cfg.cb_max_open_duration_sec
        assert cb.probe_successes_to_close == _cfg.cb_probe_successes_to_close


class TestCircuitBreakerWindowConsistency:
    """Cross-field constraint: ``min_samples <= window_size``."""

    def test_inconsistent_window_settings_rejected(self) -> None:
        """``min_samples=10 > window_size=5`` raises ``ValidationError``."""
        with pytest.raises(ValidationError, match="min_samples"):
            CircuitBreakerConfig(min_samples=10, window_size=5)

    def test_min_samples_equal_to_window_size_passes(self) -> None:
        """``min_samples=5, window_size=5`` is valid (``<=`` is inclusive)."""
        cb = CircuitBreakerConfig(min_samples=5, window_size=5)
        assert cb.min_samples == 5
        assert cb.window_size == 5

    def test_min_samples_less_than_window_size_passes(self) -> None:
        """``min_samples=3, window_size=20`` is valid."""
        cb = CircuitBreakerConfig(min_samples=3, window_size=20)
        assert cb.min_samples == 3
        assert cb.window_size == 20


class TestCircuitBreakerFieldBoundaries:
    """Pydantic field-level constraints — one test per boundary."""

    # --- min_samples (ge=1) ---

    def test_min_samples_zero_rejected(self) -> None:
        """``ge=1``: ``min_samples=0`` rejected.  # boundary: minimum window samples."""
        with pytest.raises(ValidationError) as exc_info:
            CircuitBreakerConfig(min_samples=0)
        errors = exc_info.value.errors()
        assert any("min_samples" in str(e.get("loc", "")) for e in errors)

    def test_min_samples_negative_rejected(self) -> None:
        """``ge=1``: ``min_samples=-1`` rejected.  # boundary: negative window samples."""
        with pytest.raises(ValidationError) as exc_info:
            CircuitBreakerConfig(min_samples=-1)
        errors = exc_info.value.errors()
        assert any("min_samples" in str(e.get("loc", "")) for e in errors)

    # --- window_size (ge=1) ---

    def test_window_size_zero_rejected(self) -> None:
        """``ge=1``: ``window_size=0`` rejected.  # boundary: zero window size."""
        with pytest.raises(ValidationError) as exc_info:
            CircuitBreakerConfig(window_size=0)
        errors = exc_info.value.errors()
        assert any("window_size" in str(e.get("loc", "")) for e in errors)

    def test_window_size_negative_rejected(self) -> None:
        """``ge=1``: ``window_size=-1`` rejected.  # boundary: negative window size."""
        with pytest.raises(ValidationError) as exc_info:
            CircuitBreakerConfig(window_size=-1)
        errors = exc_info.value.errors()
        assert any("window_size" in str(e.get("loc", "")) for e in errors)

    # --- error_rate_threshold (gt=0.0, le=1.0) ---

    def test_error_rate_threshold_zero_rejected(self) -> None:
        """``gt=0.0``: ``error_rate_threshold=0.0`` rejected.  # boundary: zero error threshold."""
        with pytest.raises(ValidationError) as exc_info:
            CircuitBreakerConfig(error_rate_threshold=0.0)
        errors = exc_info.value.errors()
        assert any("error_rate_threshold" in str(e.get("loc", "")) for e in errors)

    def test_error_rate_threshold_above_one_rejected(self) -> None:
        """``le=1.0``: ``error_rate_threshold=1.5`` rejected.  # boundary: over 100% threshold."""
        with pytest.raises(ValidationError) as exc_info:
            CircuitBreakerConfig(error_rate_threshold=1.5)
        errors = exc_info.value.errors()
        assert any("error_rate_threshold" in str(e.get("loc", "")) for e in errors)

    def test_error_rate_threshold_exactly_one_passes(self) -> None:
        """``le=1.0``: ``error_rate_threshold=1.0`` is valid (inclusive).  # boundary: exactly 100%."""
        cb = CircuitBreakerConfig(error_rate_threshold=1.0)
        assert cb.error_rate_threshold == 1.0

    # --- backoff_factor (ge=1.0) ---

    def test_backoff_factor_below_one_rejected(self) -> None:
        """``ge=1.0``: ``backoff_factor=0.5`` rejected.  # boundary: sub-1.0 backoff."""
        with pytest.raises(ValidationError) as exc_info:
            CircuitBreakerConfig(backoff_factor=0.5)
        errors = exc_info.value.errors()
        assert any("backoff_factor" in str(e.get("loc", "")) for e in errors)

    def test_backoff_factor_exactly_one_passes(self) -> None:
        """``ge=1.0``: ``backoff_factor=1.0`` is valid.  # boundary: exactly 1.0."""
        cb = CircuitBreakerConfig(backoff_factor=1.0)
        assert cb.backoff_factor == 1.0

    # --- open_duration_sec (gt=0) ---

    def test_open_duration_sec_zero_rejected(self) -> None:
        """``gt=0``: ``open_duration_sec=0.0`` rejected.  # boundary: zero cooldown."""
        with pytest.raises(ValidationError) as exc_info:
            CircuitBreakerConfig(open_duration_sec=0.0)
        errors = exc_info.value.errors()
        assert any("open_duration_sec" in str(e.get("loc", "")) for e in errors)

    def test_open_duration_sec_negative_rejected(self) -> None:
        """``gt=0``: ``open_duration_sec=-1.0`` rejected.  # boundary: negative cooldown."""
        with pytest.raises(ValidationError) as exc_info:
            CircuitBreakerConfig(open_duration_sec=-1.0)
        errors = exc_info.value.errors()
        assert any("open_duration_sec" in str(e.get("loc", "")) for e in errors)

    # --- max_open_duration_sec (gt=0) ---

    def test_max_open_duration_sec_zero_rejected(self) -> None:
        """``gt=0``: ``max_open_duration_sec=0.0`` rejected.  # boundary: zero max cooldown."""
        with pytest.raises(ValidationError) as exc_info:
            CircuitBreakerConfig(max_open_duration_sec=0.0)
        errors = exc_info.value.errors()
        assert any("max_open_duration_sec" in str(e.get("loc", "")) for e in errors)

    # --- max_open_duration_sec >= open_duration_sec ---

    def test_max_open_less_than_open_rejected(self) -> None:
        """``max_open_duration_sec=10 < open_duration_sec=30`` rejected.  # boundary: max < base cooldown."""
        with pytest.raises(ValidationError, match="max_open_duration_sec"):
            CircuitBreakerConfig(open_duration_sec=30.0, max_open_duration_sec=10.0)

    # --- probe_successes_to_close (ge=1) ---

    def test_probe_successes_to_close_zero_rejected(self) -> None:
        """``ge=1``: ``probe_successes_to_close=0`` rejected.  # boundary: zero probes to close."""
        with pytest.raises(ValidationError) as exc_info:
            CircuitBreakerConfig(probe_successes_to_close=0)
        errors = exc_info.value.errors()
        assert any("probe_successes_to_close" in str(e.get("loc", "")) for e in errors)

    def test_probe_successes_to_close_negative_rejected(self) -> None:
        """``ge=1``: ``probe_successes_to_close=-1`` rejected.  # boundary: negative probe count."""
        with pytest.raises(ValidationError) as exc_info:
            CircuitBreakerConfig(probe_successes_to_close=-1)
        errors = exc_info.value.errors()
        assert any("probe_successes_to_close" in str(e.get("loc", "")) for e in errors)


class TestCircuitBreakerExtraFields:
    """``extra='forbid'`` — unknown fields rejected."""

    def test_extra_fields_forbidden(self) -> None:
        """Unknown field raises ``ValidationError``."""
        with pytest.raises(ValidationError) as exc_info:
            CircuitBreakerConfig(unknown_field=True)  # type: ignore[call-arg]

        errors = exc_info.value.errors()
        assert any(
            e.get("type") == "extra_forbidden" or "extra" in str(e.get("type", ""))
            for e in errors
        )


class TestCircuitBreakerToParams:
    """``to_params()`` conversion to ``CircuitBreakerParams`` dataclass."""

    def test_to_params_converts_to_circuit_breaker_params(self) -> None:
        """Explicit config values survive the ``to_params()`` round-trip."""
        cb = CircuitBreakerConfig(
            window_size=_cfg.cb_window_size,
            error_rate_threshold=_cfg.cb_error_rate_threshold,
            min_samples=_cfg.cb_min_samples,
            open_duration_sec=_cfg.cb_open_duration_sec,
            backoff_factor=_cfg.cb_backoff_factor,
            max_open_duration_sec=_cfg.cb_max_open_duration_sec,
            probe_successes_to_close=_cfg.cb_probe_successes_to_close,
        )

        params = cb.to_params()

        assert isinstance(params, CircuitBreakerParams)
        assert params.window_size == _cfg.cb_window_size
        assert params.error_rate_threshold == _cfg.cb_error_rate_threshold
        assert params.min_samples == _cfg.cb_min_samples
        assert params.open_duration_sec == _cfg.cb_open_duration_sec
        assert params.backoff_factor == _cfg.cb_backoff_factor
        assert params.max_open_duration_sec == _cfg.cb_max_open_duration_sec
        assert params.probe_successes_to_close == _cfg.cb_probe_successes_to_close

    def test_to_params_with_defaults(self) -> None:
        """Default-constructed config converts to params with canonical defaults."""
        cb = CircuitBreakerConfig()
        params = cb.to_params()

        assert isinstance(params, CircuitBreakerParams)
        assert params.window_size == _cfg.cb_window_size
        assert params.error_rate_threshold == _cfg.cb_error_rate_threshold
        assert params.min_samples == _cfg.cb_min_samples
        assert params.open_duration_sec == _cfg.cb_open_duration_sec
        assert params.backoff_factor == _cfg.cb_backoff_factor
        assert params.max_open_duration_sec == _cfg.cb_max_open_duration_sec
        assert params.probe_successes_to_close == _cfg.cb_probe_successes_to_close
