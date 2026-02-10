# src/config/__init__.py

"""Unified Configuration Management Package.

This package provides a centralized system for loading, validating, and accessing
application configuration. It implements a Singleton pattern to ensure that the
configuration is loaded only once and is globally accessible.

Usage:
    from src.config import load_config, get_config, ConfigAccessor

    # In the main entry point of the application:
    config = load_config("config/providers.yaml")

    # In any other part of the application:
    config_obj = get_config()
    accessor = ConfigAccessor(config_obj)
    db_dsn = accessor.get_database_dsn()
"""

# Import key components to expose them at the package level.
# This follows Step 2 of the plan to create a clean public API.
from src.config.loader import ConfigLoader

# from src.core.accessor import ConfigAccessor
from src.config.schemas import Config
from src.config.validator import ConfigValidator

# This variable will hold the single, global instance of the loaded configuration.
# This is the core of the Singleton pattern implementation, as per Step 3 of the plan.
_config_instance: Config | None = None


def load_config(config_path: str = "config/providers.yaml") -> Config:
    """
    Loads, validates, and initializes the global configuration instance.
    This function should be called once when the application starts.

    Args:
        config_path: Path to the main YAML configuration file.

    Returns:
        The loaded and validated Config object.
    """
    global _config_instance

    # Instantiate the loader and validator
    loader = ConfigLoader(path=config_path)
    validator = ConfigValidator()

    # Load the raw config, validate it, and store the final object.
    loaded_config = loader.load()
    validator.validate(loaded_config)

    _config_instance = loaded_config
    return _config_instance


def get_config() -> Config:
    """
    Retrieves the globally accessible configuration instance.

    Returns:
        The loaded Config object.

    Raises:
        RuntimeError: If the configuration has not been loaded yet via load_config().
    """
    if _config_instance is None:
        # This check handles a potential error identified in the planning phase.
        raise RuntimeError("Configuration not loaded. Call load_config() first.")
    return _config_instance


# Define the public API of this package.
__all__ = [
    "Config",
    "ConfigLoader",
    "ConfigValidator",
    #    "ConfigAccessor",
    "load_config",
    "get_config",
]
