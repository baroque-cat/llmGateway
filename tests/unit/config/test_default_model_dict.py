#!/usr/bin/env python3

"""
Unit tests verifying ``ProviderConfig.default_model`` dict[str, ModelInfo]
behaviour and the rejection of the removed ``models`` field.
"""

import pytest
from pydantic import ValidationError

from src.config.schemas import Config, ModelInfo, ProviderConfig


class TestDefaultModelDict:
    """Tests for the ``default_model: dict[str, ModelInfo]`` field."""

    def test_single_model_in_default_model(self):
        """
        Parse a provider config whose ``default_model`` section carries a single
        ``ModelInfo`` entry and verify the resulting dict shape and types.
        """
        config = Config.model_validate(
            {
                "providers": {
                    "gemini_test": {
                        "provider_type": "gemini",
                        "default_model": {
                            "gemini-2.5-flash": {
                                "endpoint_suffix": ":generateContent",
                                "test_payload": {
                                    "contents": [
                                        {"parts": [{"text": "Hello"}]}
                                    ]
                                },
                            }
                        },
                    }
                }
            }
        )

        provider = config.providers["gemini_test"]
        default_model = provider.default_model

        # Dict shape
        assert isinstance(default_model, dict), (
            "default_model must be a dict"
        )
        assert len(default_model) == 1
        assert "gemini-2.5-flash" in default_model

        # Value type
        model_info = default_model["gemini-2.5-flash"]
        assert isinstance(model_info, ModelInfo), (
            "Each value must be a ModelInfo instance"
        )

        # Field contents
        assert model_info.endpoint_suffix == ":generateContent"
        assert model_info.test_payload == {
            "contents": [{"parts": [{"text": "Hello"}]}]
        }

    def test_empty_default_model_is_valid(self):
        """
        When ``default_model`` is completely absent from the provider YAML
        section, the field defaults to an empty ``dict``.
        """
        config = Config.model_validate(
            {
                "providers": {
                    "bare_provider": {
                        "provider_type": "openai_like",
                    }
                }
            }
        )

        provider = config.providers["bare_provider"]
        default_model = provider.default_model

        assert isinstance(default_model, dict), (
            "default_model must be a dict"
        )
        assert default_model == {}, (
            "Absent default_model should resolve to an empty dict"
        )

    def test_config_validation_rejects_models_field(self):
        """
        ``ProviderConfig`` carries ``ConfigDict(extra='forbid')`` and the
        ``models`` field was removed.  Passing a ``models:`` key must therefore
        raise a ``ValidationError`` with an ``extra_forbidden`` error type.
        """
        with pytest.raises(ValidationError) as exc_info:
            Config.model_validate(
                {
                    "providers": {
                        "old_format": {
                            "provider_type": "anthropic",
                            "models": {
                                "claude-3-haiku": {}
                            },
                        }
                    }
                }
            )

        errors = exc_info.value.errors()
        extra_errors = [
            e for e in errors if e.get("type") == "extra_forbidden"
        ]
        assert extra_errors, (
            f"Expected at least one 'extra_forbidden' error but got: {errors}"
        )

        # Also confirm it mentions the offending field
        field_names = [e.get("loc", []) for e in extra_errors]
        assert any("models" in loc for loc in field_names), (
            f"Expected 'models' in error loc paths but got: {field_names}"
        )
