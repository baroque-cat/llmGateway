# src/config/loader.py

from __future__ import annotations

import logging
import os
import re
from typing import Any, cast

from deepmerge import always_merger
from dotenv import load_dotenv
from pydantic import ValidationError
from ruamel.yaml import YAML

from src.config.defaults import get_default_config
from src.config.error_formatter import handle_validation_error
from src.config.schemas import Config

# Define a recursive type alias for configuration dictionaries
type ConfigValue = str | int | float | bool | None | "ConfigDict" | list["ConfigValue"]
type ConfigDict = dict[str, ConfigValue]

logger = logging.getLogger(__name__)

# Regex to find environment variable placeholders like ${VAR_NAME}
ENV_VAR_PATTERN = re.compile(r"^\$\{(?P<name>[A-Z0-9_]+)\}$")


class ConfigLoader:
    """
    Intelligently loads, merges, and parses the application's configuration
    from a YAML file into type-safe Pydantic BaseModel objects.
    """

    def __init__(self, path: str = "config/providers.yaml"):
        """
        Initializes the ConfigLoader.
        This aligns with Step 2 of the plan.

        Args:
            path: The path to the YAML configuration file.
        """
        self.config_path = path
        self.yaml = YAML()

    def load(self) -> Config:
        """
        Orchestrates the entire configuration loading process.
        This is the main public method, as described in Step 2 of the plan.
        """
        # Step 1: Read and prepare raw data (Plan Step 3.1)
        if not os.path.exists(self.config_path):
            raise FileNotFoundError(
                f"Configuration file not found at '{self.config_path}'."
            )

        # Load environment variables from a .env file if it exists.
        if load_dotenv():
            logger.info("Loaded environment variables from .env file.")

        with open(self.config_path, encoding="utf-8") as f:
            # fmt: off
            user_config_raw = cast(dict[str, Any], self.yaml.load(f) or {})  # pyright: ignore[reportUnknownMemberType]
            # fmt: on

        # Step 2: Resolve environment variables (Plan Step 3.2)
        user_config_resolved = self._resolve_env_vars(user_config_raw)

        # Step 3 & 4: Build base config and merge (Plan Step 3.3 & 3.4)
        final_config_dict = self._build_and_merge_config(user_config_resolved)

        # Step 4a: Resolve env vars from defaults.py injected during merge
        # (Plan Step 3.5 — second pass handles defaults-originated ${VAR})
        final_config_dict = self._resolve_env_vars(final_config_dict)

        # Step 5: Validate with Pydantic (Plan Step 4.2 & 4.3)
        try:
            app_config = Config.model_validate(final_config_dict)
        except ValidationError as e:
            # Pass the original unmerged user config for line number extraction
            handle_validation_error(e, user_config_raw)
            # handle_validation_error calls sys.exit(1), so this is unreachable
            raise AssertionError("handle_validation_error should have exited") from None

        logger.info("Configuration loaded and parsed successfully.")

        # Step 6: Return the result
        return app_config

    def _resolve_env_vars(self, config_value: Any) -> Any:
        """
        Recursively traverses a config structure and replaces ${VAR_NAME} placeholders.
        This helper function implements the logic from Step 3.2 of the plan and
        addresses a potential error scenario from the analysis.
        """
        if isinstance(config_value, dict):
            # fmt: off
            return {k: self._resolve_env_vars(v) for k, v in config_value.items()}  # pyright: ignore[reportUnknownVariableType]
            # fmt: on

        if isinstance(config_value, list):
            # fmt: off
            return [self._resolve_env_vars(item) for item in config_value]  # pyright: ignore[reportUnknownVariableType]
            # fmt: on

        if isinstance(config_value, str):
            match = ENV_VAR_PATTERN.match(config_value)
            if match:
                var_name = match.group("name")
                var_value = os.environ.get(var_name)
                if var_value is None:
                    raise ValueError(
                        f"Configuration error: Environment variable '{var_name}' is not set, but is required by the config."
                    )
                return var_value

        return config_value

    def _build_and_merge_config(self, user_config: dict[str, Any]) -> dict[str, Any]:
        """
        Constructs the full configuration dictionary by merging user-defined values
        on top of layered defaults and templates. This is the core logic.
        """
        # Start with the absolute base defaults from schemas (via get_default_config)
        base_config = get_default_config()

        # Merge user's global settings over the base defaults.
        # This uses the 'always_merger' from the deepmerge library, as planned.
        final_config = always_merger.merge(base_config, user_config)

        # Now, handle the providers section with special template-based logic.
        final_providers = {}
        user_providers = user_config.get("providers", {})

        for name, user_provider_conf in user_providers.items():
            # This check handles a potential error we identified: missing provider_type.
            provider_type = user_provider_conf.get("provider_type")
            if not provider_type:
                raise ValueError(
                    f"Provider '{name}' must have a 'provider_type' defined in the configuration."
                )

            # 1. Start with the generic provider template from defaults.py
            provider_base = get_default_config()["providers"]["llm_provider_default"]

            # 2. Merge the user's specific configuration for this instance.
            # Since we have removed automatic template injection (provider_templates.py),
            # the user config must contain all necessary fields (api_base_url, models, etc.).
            final_provider_instance = always_merger.merge(
                provider_base, user_provider_conf
            )

            final_providers[name] = final_provider_instance

        final_config["providers"] = final_providers
        return final_config
