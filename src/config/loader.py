# src/config/loader.py

from __future__ import annotations

import logging
import os
import re
from dataclasses import fields, is_dataclass
from typing import (
    Any,
    TypeVar,
    cast,
    get_args,
    get_origin,
    get_type_hints,
)

from deepmerge import always_merger
from dotenv import load_dotenv
from ruamel.yaml import YAML

from src.config.defaults import get_default_config
from src.config.schemas import Config

# Define a recursive type alias for configuration dictionaries
type ConfigValue = str | int | float | bool | None | "ConfigDict" | list["ConfigValue"]
type ConfigDict = dict[str, ConfigValue]

logger = logging.getLogger(__name__)

# This is a generic TypeVar used for our recursive dataclass conversion.
# It allows for type hinting that returns the same type as the input class.
T = TypeVar("T")

# Regex to find environment variable placeholders like ${VAR_NAME}
ENV_VAR_PATTERN = re.compile(r"^\$\{(?P<name>[A-Z0-9_]+)\}$")


class ConfigLoader:
    """
    Intelligently loads, merges, and parses the application's configuration
    from a YAML file into type-safe dataclass objects.
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
            user_config_raw = cast(dict[str, Any], self.yaml.load(f) or {})  # type: ignore

        # Step 2: Resolve environment variables (Plan Step 3.2)
        user_config_resolved = self._resolve_env_vars(user_config_raw)

        # Step 3 & 4: Build base config and merge (Plan Step 3.3 & 3.4)
        final_config_dict = self._build_and_merge_config(user_config_resolved)

        # Step 5: Convert the final dictionary to dataclass objects (Plan Step 3.5)
        try:
            app_config = self._dict_to_dataclass(Config, final_config_dict)
        except (TypeError, ValueError) as e:
            logger.error(
                f"Failed to parse configuration into dataclasses. Check for type mismatches in your YAML. Error: {e}"
            )
            raise TypeError(f"Configuration parsing error: {e}") from e

        logger.info("Configuration loaded and parsed successfully.")

        # Step 6: Return the result, ready for the validator (Plan Step 3.6)
        return app_config

    def _resolve_env_vars(self, config_value: Any) -> Any:
        """
        Recursively traverses a config structure and replaces ${VAR_NAME} placeholders.
        This helper function implements the logic from Step 3.2 of the plan and
        addresses a potential error scenario from the analysis.
        """
        if isinstance(config_value, dict):
            return {k: self._resolve_env_vars(v) for k, v in config_value.items()}  # type: ignore

        if isinstance(config_value, list):
            return [self._resolve_env_vars(item) for item in config_value]  # type: ignore

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

    def _dict_to_dataclass(self, dclass: type[T], data: dict[str, Any]) -> T:
        """
        Recursively converts a dictionary to a dataclass instance.
        """
        if not is_dataclass(dclass):
            raise TypeError(f"Expected a dataclass type, but got {dclass}")

        type_hints = get_type_hints(dclass)
        field_data = {}

        for f in fields(dclass):
            if f.name in data:
                field_value = data[f.name]
                field_type = type_hints[f.name]
                origin_type = get_origin(field_type)

                if origin_type is dict:
                    # Handle nested dictionaries of dataclasses
                    args = get_args(field_type)
                    if len(args) == 2:
                        item_type = args[1]
                        if is_dataclass(item_type) and isinstance(item_type, type):
                            field_data[f.name] = {
                                k: self._dict_to_dataclass(item_type, v)
                                for k, v in field_value.items()
                            }
                        else:
                            field_data[f.name] = field_value
                    else:
                        field_data[f.name] = field_value

                elif origin_type is list:
                    # Handle lists of dataclasses
                    args = get_args(field_type)
                    if args:
                        item_type = args[0]
                        if is_dataclass(item_type) and isinstance(item_type, type):
                            field_data[f.name] = [
                                self._dict_to_dataclass(item_type, item)
                                for item in field_value
                            ]
                        else:
                            field_data[f.name] = field_value
                    else:
                        field_data[f.name] = field_value

                elif is_dataclass(field_type) and isinstance(field_type, type):
                    # Handle nested single dataclasses
                    field_data[f.name] = self._dict_to_dataclass(
                        field_type, field_value
                    )
                else:
                    # Handle primitive types
                    field_data[f.name] = field_value

        return dclass(**field_data)
