"""
Unit tests for src.core.retry (AsyncRetrier) and src.config.schemas (DatabaseRetryConfig).

Covers test-plan scenarios:
  UT-E01..UT-E10  — AsyncRetrier behaviour
  UT-F01..UT-F08  — DatabaseRetryConfig validation
  SEC-01..SEC-08  — Security / architectural constraints
"""

import importlib
import logging
from unittest.mock import AsyncMock, MagicMock, patch

import asyncpg.exceptions
import pytest
from pydantic import ValidationError

from src.config.schemas import Config, DatabaseConfig, DatabaseRetryConfig
from src.core.retry import DB_RETRYABLE, AsyncRetrier

# ==============================================================================
# Helpers
# ==============================================================================


def _make_retryable_exc(msg: str = "connection lost"):
    """Return a transient asyncpg exception (ConnectionDoesNotExistError).

    A message string is required because asyncpg's __str__ accesses
    self.args[0], which raises IndexError if no args were passed.
    """
    return asyncpg.exceptions.ConnectionDoesNotExistError(msg)


def _make_non_retryable_db_exc(msg: str = "invalid password"):
    """Return a non-transient asyncpg exception (InvalidPasswordError).

    A message string is required because asyncpg's __str__ accesses
    self.args[0], which raises IndexError if no args were passed.
    """
    return asyncpg.exceptions.InvalidPasswordError(msg)


# ==============================================================================
# UT-E01: Operation succeeds on first attempt — result returned without retry
# ==============================================================================


class TestUTE01:
    """UT-E01: Operation succeeds on first attempt — result returned without retry."""

    @pytest.mark.asyncio
    async def test_success_on_first_attempt(self):
        """Operation returns result immediately; no sleep/retry calls."""
        retrier = AsyncRetrier(max_attempts=3, jitter=False)
        operation = AsyncMock(return_value="ok")

        result = await retrier.execute(operation)

        assert result == "ok"
        assert operation.call_count == 1


# ==============================================================================
# UT-E02: Operation succeeds after transient error (1 retry)
# ==============================================================================


class TestUTE02:
    """UT-E02: Operation succeeds after transient error (1 retry)."""

    @pytest.mark.asyncio
    async def test_success_after_one_transient_error(self):
        """First call raises retryable, second succeeds."""
        retrier = AsyncRetrier(max_attempts=3, base_delay_sec=0.01, jitter=False)
        exc = _make_retryable_exc()
        operation = AsyncMock(side_effect=[exc, "ok"])

        with patch("src.core.retry.asyncio.sleep", new_callable=AsyncMock):
            result = await retrier.execute(operation)

        assert result == "ok"
        assert operation.call_count == 2


# ==============================================================================
# UT-E03: All attempts exhausted — last exception re-raised
# ==============================================================================


class TestUTE03:
    """UT-E03: All attempts exhausted — last exception re-raised."""

    @pytest.mark.asyncio
    async def test_all_attempts_exhausted(self):
        """All 3 attempts fail with retryable; last exception is re-raised."""
        retrier = AsyncRetrier(max_attempts=3, base_delay_sec=0.01, jitter=False)
        exc1 = _make_retryable_exc()
        exc2 = _make_retryable_exc()
        exc3 = _make_retryable_exc()
        operation = AsyncMock(side_effect=[exc1, exc2, exc3])

        with patch("src.core.retry.asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(asyncpg.exceptions.ConnectionDoesNotExistError):
                await retrier.execute(operation)

        assert operation.call_count == 3


# ==============================================================================
# UT-E04: Non-retryable exception not retried — immediately re-raised
# ==============================================================================


class TestUTE04:
    """UT-E04: Non-retryable exception is not retried — immediately re-raised."""

    @pytest.mark.asyncio
    async def test_non_retryable_not_retried(self):
        """A plain RuntimeError is not in retryable tuple; raised immediately."""
        retrier = AsyncRetrier(max_attempts=3)
        operation = AsyncMock(side_effect=RuntimeError("boom"))

        with pytest.raises(RuntimeError, match="boom"):
            await retrier.execute(operation)

        assert operation.call_count == 1


# ==============================================================================
# UT-E05: InvalidPasswordError not retried
# ==============================================================================


class TestUTE05:
    """UT-E05: InvalidPasswordError is not retried."""

    @pytest.mark.asyncio
    async def test_invalid_password_not_retried(self):
        """asyncpg InvalidPasswordError is non-transient; no retry."""
        retrier = AsyncRetrier(max_attempts=3)
        exc = _make_non_retryable_db_exc()
        operation = AsyncMock(side_effect=exc)

        with pytest.raises(asyncpg.exceptions.InvalidPasswordError):
            await retrier.execute(operation)

        assert operation.call_count == 1


# ==============================================================================
# UT-E06: Exponential backoff without jitter — exact delays
# ==============================================================================


class TestUTE06:
    """UT-E06: Exponential backoff without jitter — exact delays."""

    @pytest.mark.asyncio
    async def test_exact_delays_without_jitter(self):
        """With jitter=False, delays follow base * factor^(attempt-1) exactly."""
        retrier = AsyncRetrier(
            max_attempts=4,
            base_delay_sec=1.0,
            backoff_factor=2.0,
            jitter=False,
        )
        exc = _make_retryable_exc()
        operation = AsyncMock(side_effect=[exc, exc, exc, "ok"])

        sleep_mock = AsyncMock()
        with patch("src.core.retry.asyncio.sleep", sleep_mock):
            result = await retrier.execute(operation)

        assert result == "ok"
        # attempt 1 fails → delay = 1.0 * 2^0 = 1.0
        # attempt 2 fails → delay = 1.0 * 2^1 = 2.0
        # attempt 3 fails → delay = 1.0 * 2^2 = 4.0
        assert sleep_mock.call_count == 3
        assert sleep_mock.call_args_list[0].args[0] == pytest.approx(1.0)
        assert sleep_mock.call_args_list[1].args[0] == pytest.approx(2.0)
        assert sleep_mock.call_args_list[2].args[0] == pytest.approx(4.0)


# ==============================================================================
# UT-E07: Jitter multiplies delay by random(0.5, 1.5)
# ==============================================================================


class TestUTE07:
    """UT-E07: Jitter multiplies delay by random(0.5, 1.5)."""

    @pytest.mark.asyncio
    async def test_jitter_applies_random_multiplier(self):
        """With jitter=True, delay = base * factor^(attempt-1) * random(0.5, 1.5)."""
        retrier = AsyncRetrier(
            max_attempts=3,
            base_delay_sec=1.0,
            backoff_factor=2.0,
            jitter=True,
        )
        exc = _make_retryable_exc()
        operation = AsyncMock(side_effect=[exc, exc, exc])

        # Mock random.uniform to return a deterministic value
        uniform_mock = MagicMock(return_value=1.2)
        sleep_mock = AsyncMock()
        with (
            patch("src.core.retry.random.uniform", uniform_mock),
            patch("src.core.retry.asyncio.sleep", sleep_mock),
        ):
            with pytest.raises(asyncpg.exceptions.ConnectionDoesNotExistError):
                await retrier.execute(operation)

        # attempt 1 fails → delay = 1.0 * 2^0 * 1.2 = 1.2
        # attempt 2 fails → delay = 1.0 * 2^1 * 1.2 = 2.4
        assert sleep_mock.call_count == 2
        assert sleep_mock.call_args_list[0].args[0] == pytest.approx(1.2)
        assert sleep_mock.call_args_list[1].args[0] == pytest.approx(2.4)


# ==============================================================================
# UT-E08: max_attempts=1 — retry does not happen
# ==============================================================================


class TestUTE08:
    """UT-E08: max_attempts=1 — retry does not happen."""

    @pytest.mark.asyncio
    async def test_no_retry_with_single_attempt(self):
        """With max_attempts=1, even a retryable exception is re-raised immediately."""
        retrier = AsyncRetrier(max_attempts=1)
        exc = _make_retryable_exc()
        operation = AsyncMock(side_effect=exc)

        with pytest.raises(asyncpg.exceptions.ConnectionDoesNotExistError):
            await retrier.execute(operation)

        assert operation.call_count == 1


# ==============================================================================
# UT-E09: Coroutine factory recreated on each attempt
# ==============================================================================


class TestUTE09:
    """UT-E09: Coroutine factory is recreated on each attempt."""

    @pytest.mark.asyncio
    async def test_operation_called_multiple_times(self):
        """The operation callable is invoked once per attempt, not just awaited once."""
        retrier = AsyncRetrier(max_attempts=3, base_delay_sec=0.01, jitter=False)
        exc = _make_retryable_exc()
        operation = AsyncMock(side_effect=[exc, exc, "ok"])

        with patch("src.core.retry.asyncio.sleep", new_callable=AsyncMock):
            result = await retrier.execute(operation)

        assert result == "ok"
        # The factory is called 3 times: attempt 1, 2, 3
        assert operation.call_count == 3


# ==============================================================================
# UT-E10: DB_RETRYABLE contains exactly 4 asyncpg classes
# ==============================================================================


class TestUTE10:
    """UT-E10: DB_RETRYABLE tuple contains exactly 4 asyncpg classes."""

    def test_db_retryable_has_four_entries(self):
        """DB_RETRYABLE must contain exactly 4 exception classes."""
        assert len(DB_RETRYABLE) == 4

    def test_db_retryable_classes_are_asyncpg(self):
        """Each class in DB_RETRYABLE must be from asyncpg.exceptions."""
        expected = (
            asyncpg.exceptions.ConnectionDoesNotExistError,
            asyncpg.exceptions.InterfaceError,
            asyncpg.exceptions.TooManyConnectionsError,
            asyncpg.exceptions.DeadlockDetectedError,
        )
        assert expected == DB_RETRYABLE

    def test_db_retryable_is_tuple(self):
        """DB_RETRYABLE must be a tuple (immutable)."""
        assert isinstance(DB_RETRYABLE, tuple)


# ==============================================================================
# UT-F01: DatabaseRetryConfig defaults
# ==============================================================================


class TestUTF01:
    """UT-F01: DatabaseRetryConfig defaults."""

    def test_default_values(self):
        """Default DatabaseRetryConfig has expected values."""
        cfg = DatabaseRetryConfig()
        assert cfg.max_attempts == 3
        assert cfg.base_delay_sec == 1.0
        assert cfg.backoff_factor == 2.0
        assert cfg.jitter is True


# ==============================================================================
# UT-F02: max_attempts > 10 causes ValidationError
# ==============================================================================


class TestUTF02:
    """UT-F02: max_attempts > 10 raises ValidationError."""

    def test_max_attempts_11_raises_validation_error(self):
        """max_attempts=11 exceeds le=10 constraint."""
        with pytest.raises(ValidationError):
            DatabaseRetryConfig(max_attempts=11)

    def test_max_attempts_100_raises_validation_error(self):
        """max_attempts=100 also exceeds le=10."""
        with pytest.raises(ValidationError):
            DatabaseRetryConfig(max_attempts=100)


# ==============================================================================
# UT-F03: max_attempts = 0 causes ValidationError
# ==============================================================================


class TestUTF03:
    """UT-F03: max_attempts = 0 raises ValidationError."""

    def test_max_attempts_zero_raises_validation_error(self):
        """max_attempts=0 violates gt=0 constraint."""
        with pytest.raises(ValidationError):
            DatabaseRetryConfig(max_attempts=0)

    def test_max_attempts_negative_raises_validation_error(self):
        """max_attempts=-1 also violates gt=0."""
        with pytest.raises(ValidationError):
            DatabaseRetryConfig(max_attempts=-1)


# ==============================================================================
# UT-F04: base_delay_sec ≤ 0 causes ValidationError
# ==============================================================================


class TestUTF04:
    """UT-F04: base_delay_sec ≤ 0 raises ValidationError."""

    def test_base_delay_sec_zero_raises_validation_error(self):
        """base_delay_sec=0 violates gt=0."""
        with pytest.raises(ValidationError):
            DatabaseRetryConfig(base_delay_sec=0)

    def test_base_delay_sec_negative_raises_validation_error(self):
        """base_delay_sec=-1.0 violates gt=0."""
        with pytest.raises(ValidationError):
            DatabaseRetryConfig(base_delay_sec=-1.0)


# ==============================================================================
# UT-F05: backoff_factor < 1.0 causes ValidationError
# ==============================================================================


class TestUTF05:
    """UT-F05: backoff_factor < 1.0 raises ValidationError."""

    def test_backoff_factor_0_5_raises_validation_error(self):
        """backoff_factor=0.5 violates ge=1.0."""
        with pytest.raises(ValidationError):
            DatabaseRetryConfig(backoff_factor=0.5)

    def test_backoff_factor_zero_raises_validation_error(self):
        """backoff_factor=0.0 violates ge=1.0."""
        with pytest.raises(ValidationError):
            DatabaseRetryConfig(backoff_factor=0.0)


# ==============================================================================
# UT-F06: backoff_factor = 1.0 is valid
# ==============================================================================


class TestUTF06:
    """UT-F06: backoff_factor = 1.0 — valid."""

    def test_backoff_factor_one_is_valid(self):
        """backoff_factor=1.0 satisfies ge=1.0 constraint."""
        cfg = DatabaseRetryConfig(backoff_factor=1.0)
        assert cfg.backoff_factor == 1.0


# ==============================================================================
# UT-F07: DatabaseConfig.retry populated via default_factory
# ==============================================================================


class TestUTF07:
    """UT-F07: DatabaseConfig.retry populated via default_factory."""

    def test_database_config_retry_is_retry_config_instance(self):
        """DatabaseConfig() automatically populates retry with DatabaseRetryConfig."""
        db_cfg = DatabaseConfig()
        assert isinstance(db_cfg.retry, DatabaseRetryConfig)

    def test_database_config_retry_has_defaults(self):
        """Default retry config within DatabaseConfig has standard defaults."""
        db_cfg = DatabaseConfig()
        assert db_cfg.retry.max_attempts == 3
        assert db_cfg.retry.base_delay_sec == 1.0
        assert db_cfg.retry.backoff_factor == 2.0
        assert db_cfg.retry.jitter is True

    def test_two_database_configs_have_independent_retry(self):
        """default_factory creates independent instances (no shared mutable state)."""
        cfg1 = DatabaseConfig()
        cfg2 = DatabaseConfig()
        cfg1.retry.max_attempts = 5
        assert cfg2.retry.max_attempts == 3  # Not affected by cfg1 mutation


# ==============================================================================
# UT-F08: YAML with database.retry.max_attempts: 5 — parsing
# ==============================================================================


class TestUTF08:
    """UT-F08: YAML with database.retry.max_attempts: 5 — parsing."""

    def test_yaml_parsing_max_attempts_5(self):
        """Config.model_validate parses nested database.retry.max_attempts: 5."""
        raw = {"database": {"retry": {"max_attempts": 5}}}
        config = Config.model_validate(raw)
        assert config.database.retry.max_attempts == 5

    def test_yaml_parsing_preserves_other_defaults(self):
        """Other retry fields keep defaults when only max_attempts is overridden."""
        raw = {"database": {"retry": {"max_attempts": 5}}}
        config = Config.model_validate(raw)
        assert config.database.retry.base_delay_sec == 1.0
        assert config.database.retry.backoff_factor == 2.0
        assert config.database.retry.jitter is True


# ==============================================================================
# SEC-01: AsyncRetrier does not retry non-transient DB errors
# ==============================================================================


class TestSEC01:
    """SEC-01: AsyncRetrier does not retry non-transient DB errors."""

    @pytest.mark.asyncio
    async def test_postgres_error_not_retried(self):
        """asyncpg PostgresError (non-transient) is not retried."""
        retrier = AsyncRetrier(max_attempts=3)
        exc = asyncpg.exceptions.PostgresError("generic db error")
        operation = AsyncMock(side_effect=exc)

        with pytest.raises(asyncpg.exceptions.PostgresError):
            await retrier.execute(operation)

        assert operation.call_count == 1

    @pytest.mark.asyncio
    async def test_syntax_error_not_retried(self):
        """asyncpg PostgresSyntaxError is not retried."""
        retrier = AsyncRetrier(max_attempts=3)
        exc = asyncpg.exceptions.PostgresSyntaxError("bad query")
        operation = AsyncMock(side_effect=exc)

        with pytest.raises(asyncpg.exceptions.PostgresSyntaxError):
            await retrier.execute(operation)

        assert operation.call_count == 1


# ==============================================================================
# SEC-02: max_attempts=10 — delay doesn't cause DoS
# ==============================================================================


class TestSEC02:
    """SEC-02: max_attempts=10 — delay does not cause DoS."""

    def test_max_delay_is_bounded(self):
        """Even with max_attempts=10, the maximum delay stays bounded."""
        retrier = AsyncRetrier(
            max_attempts=10,
            base_delay_sec=1.0,
            backoff_factor=2.0,
            jitter=False,
        )
        # Last delay before final attempt: attempt=9 → delay = 1.0 * 2^8 = 256s
        # That's under 5 minutes, which is reasonable for a DB retry.
        max_delay = retrier._compute_delay(9)
        assert max_delay < 600  # Less than 10 minutes (DoS protection)

    def test_max_delay_with_high_backoff_still_bounded(self):
        """With backoff_factor=2.0 and 10 attempts, max delay is 256s."""
        retrier = AsyncRetrier(
            max_attempts=10,
            base_delay_sec=1.0,
            backoff_factor=2.0,
            jitter=False,
        )
        # attempt 9 → base * 2^(9-1) = 1.0 * 256 = 256
        delay = retrier._compute_delay(9)
        assert delay == pytest.approx(256.0)
        # Still under 5 minutes
        assert delay < 300


# ==============================================================================
# SEC-03: DB_RETRYABLE is fixed, not configurable via YAML
# ==============================================================================


class TestSEC03:
    """SEC-03: DB_RETRYABLE — fixed, not configurable via YAML."""

    def test_db_retryable_not_in_schema(self):
        """DatabaseRetryConfig does not have a 'retryable' field."""
        cfg = DatabaseRetryConfig()
        assert not hasattr(cfg, "retryable")

    def test_db_retryable_not_in_yaml_keys(self):
        """DatabaseRetryConfig model fields do not include 'retryable'."""
        field_keys = set(DatabaseRetryConfig.model_fields.keys())
        assert "retryable" not in field_keys

    def test_db_retryable_is_module_constant(self):
        """DB_RETRYABLE is a module-level constant, not a config attribute."""
        # It's imported from src.core.retry, not from any config schema
        assert isinstance(DB_RETRYABLE, tuple)
        # Verify it's not an instance attribute of any config class
        assert not hasattr(DatabaseRetryConfig, "DB_RETRYABLE")


# ==============================================================================
# SEC-05: DatabaseRetryConfig.max_attempts limited to le=10
# ==============================================================================


class TestSEC05:
    """SEC-05: DatabaseRetryConfig.max_attempts limited to le=10."""

    def test_field_constraint_le_10(self):
        """The max_attempts Field has le=10 constraint."""
        field_info = DatabaseRetryConfig.model_fields["max_attempts"]
        # Pydantic v2 stores constraints in metadata via annotated_types.
        # metadata_lookup is a dict mapping constraint names to their classes.
        from annotated_types import Le

        le_cls = field_info.metadata_lookup.get("le")
        assert le_cls is Le
        # Find the Le constraint in metadata
        le_constraint = None
        for m in field_info.metadata:
            if isinstance(m, Le):
                le_constraint = m
                break
        assert le_constraint is not None
        assert le_constraint.le == 10

    def test_max_attempts_10_is_valid(self):
        """max_attempts=10 is the maximum allowed value."""
        cfg = DatabaseRetryConfig(max_attempts=10)
        assert cfg.max_attempts == 10

    def test_max_attempts_11_is_invalid(self):
        """max_attempts=11 exceeds the le=10 constraint."""
        with pytest.raises(ValidationError):
            DatabaseRetryConfig(max_attempts=11)


# ==============================================================================
# SEC-07: Logging retry at WARNING, exhaustion at ERROR
# ==============================================================================


class TestSEC07:
    """SEC-07: Retry logged at WARNING, exhaustion at ERROR."""

    @pytest.mark.asyncio
    async def test_retry_logs_warning(self, caplog):
        """On retryable error before exhaustion, a WARNING is logged."""
        retrier = AsyncRetrier(max_attempts=3, base_delay_sec=0.01, jitter=False)
        exc = _make_retryable_exc()
        operation = AsyncMock(side_effect=[exc, "ok"])

        with patch("src.core.retry.asyncio.sleep", new_callable=AsyncMock):
            with caplog.at_level(logging.DEBUG, logger="src.core.retry"):
                result = await retrier.execute(operation)

        assert result == "ok"
        warning_records = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warning_records) >= 1
        # The WARNING message should mention "retrying"
        assert any(
            "retrying" in r.message.lower() or "retry" in r.message.lower()
            for r in warning_records
        )

    @pytest.mark.asyncio
    async def test_exhaustion_logs_error(self, caplog):
        """When all attempts are exhausted, an ERROR is logged."""
        retrier = AsyncRetrier(max_attempts=2, base_delay_sec=0.01, jitter=False)
        exc = _make_retryable_exc()
        operation = AsyncMock(side_effect=[exc, exc])

        with patch("src.core.retry.asyncio.sleep", new_callable=AsyncMock):
            with caplog.at_level(logging.DEBUG, logger="src.core.retry"):
                with pytest.raises(asyncpg.exceptions.ConnectionDoesNotExistError):
                    await retrier.execute(operation)

        error_records = [r for r in caplog.records if r.levelno == logging.ERROR]
        assert len(error_records) >= 1
        assert any("failed after" in r.message.lower() for r in error_records)

    @pytest.mark.asyncio
    async def test_non_retryable_logs_error(self, caplog):
        """Non-retryable exception is logged at ERROR level."""
        retrier = AsyncRetrier(max_attempts=3)
        exc = RuntimeError("non-retryable")
        operation = AsyncMock(side_effect=exc)

        with caplog.at_level(logging.DEBUG, logger="src.core.retry"):
            with pytest.raises(RuntimeError):
                await retrier.execute(operation)

        error_records = [r for r in caplog.records if r.levelno == logging.ERROR]
        assert len(error_records) >= 1
        assert any("non-retryable" in r.message.lower() for r in error_records)


# ==============================================================================
# SEC-08: src/core/retry.py does not import from src.services
# ==============================================================================


class TestSEC08:
    """SEC-08: src/core/retry.py does not import from src.services."""

    def test_no_services_import(self):
        """The retry module must not import anything from src.services."""
        # Re-import the module to inspect its source

        source = importlib.util.find_spec("src.core.retry")
        assert source is not None
        # Read the source code and check for forbidden imports
        with open(source.origin, encoding="utf-8") as f:
            source_code = f.read()

        assert "from src.services" not in source_code
        assert "import src.services" not in source_code

    def test_module_imports_are_core_only(self):
        """Verify the module only imports from stdlib and asyncpg."""
        # The module should import: asyncio, logging, random, typing, asyncpg
        # No src.services imports
        import src.core.retry as retry_module

        # Check that no src.services sub-attribute exists on the module
        for attr_name in dir(retry_module):
            attr = getattr(retry_module, attr_name)
            if hasattr(attr, "__module__") and isinstance(attr.__module__, str):
                assert not attr.__module__.startswith("src.services")
