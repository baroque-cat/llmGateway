# src/core/accessor.py

from typing import Dict, Optional

# This import structure assumes that the application is run from the root
# directory and 'src' is in the Python path, as configured in main.py.
# This aligns with the project structure and avoids relative import issues.
from src.config.schemas import (
    Config,
    DatabaseConfig,
    HealthPolicyConfig,
    LoggingConfig,
    ModelInfo,
    ProviderConfig,
    WorkerConfig
)

class ConfigAccessor:
    """
    Provides a safe and convenient interface for accessing configuration values.
    
    This class acts as a "Facade" to the complex, nested Config object. It decouples
    the application's business logic from the specific structure of the configuration,
    making future refactoring of the config schemas much easier.
    This directly follows the plan to adopt the pattern from the analyzed example [9].
    """

    def __init__(self, config: Config):
        """
        Initializes the accessor with the fully loaded and validated config object.

        Args:
            config: The root Config object from the loader.
        """
        self._config = config

    # --- Step 2: Global Configuration Accessors ---
    # These methods provide direct access to top-level configuration sections.

    def get_database_config(self) -> DatabaseConfig:
        """Returns the complete database configuration object."""
        return self._config.database

    def get_database_dsn(self) -> str:
        """
        Constructs and returns the database DSN string.
        This improves upon the base plan by using the helper method from the schema.
        """
        return self._config.database.to_dsn()

    def get_worker_config(self) -> WorkerConfig:
        """Returns the complete background worker configuration object."""
        return self._config.worker

    def get_worker_concurrency(self) -> int:
        """Returns the maximum number of concurrent provider checks for the worker."""
        return self._config.worker.max_concurrent_providers

    def get_logging_config(self) -> LoggingConfig:
        """Returns the complete logging configuration object."""
        return self._config.logging

    # --- Step 3: Provider-level Accessors ---
    # These methods manage access to the dictionary of provider instances.

    def get_all_providers(self) -> Dict[str, ProviderConfig]:
        """Returns a dictionary of all configured provider instances."""
        return self._config.providers

    def get_enabled_providers(self) -> Dict[str, ProviderConfig]:
        """
        Returns a dictionary of only the enabled provider instances.
        This is a key improvement for convenience, as most services will only
        care about active providers.
        """
        return {
            name: conf for name, conf in self._config.providers.items() if conf.enabled
        }

    def get_provider(self, name: str) -> Optional[ProviderConfig]:
        """
        Safely retrieves a provider's configuration by its instance name.

        Args:
            name: The unique name of the provider instance.

        Returns:
            The ProviderConfig object if found, otherwise None. This prevents KeyErrors.
        """
        return self._config.providers.get(name)

    def get_provider_or_raise(self, name: str) -> ProviderConfig:
        """
        Retrieves a provider's configuration, raising an error if not found.
        Useful for contexts where the provider's existence is guaranteed.

        Args:
            name: The unique name of the provider instance.

        Returns:
            The ProviderConfig object.
        
        Raises:
            KeyError: If no provider with the given name is found.
        """
        if name not in self._config.providers:
            raise KeyError(f"Provider instance '{name}' not found in configuration.")
        return self._config.providers[name]

    # --- Step 4: Detailed "Getter" Methods ---
    # These methods provide convenient access to specific, often nested,
    # configuration values for a given provider. This is the core value of the accessor.

    def get_gateway_token_for_provider(self, name: str) -> Optional[str]:
        """
        Retrieves the gateway access token for a specific provider instance.
        
        Args:
            name: The name of the provider instance.
            
        Returns:
            The token string, or None if the provider does not exist.
        """
        provider = self.get_provider(name)
        return provider.access_control.gateway_access_token if provider else None

    def get_health_policy(self, name: str) -> Optional[HealthPolicyConfig]:
        """
        Retrieves the health check policy for a specific provider instance.

        Args:
            name: The name of the provider instance.

        Returns:
            The HealthPolicyConfig object, or None if the provider does not exist.
        """
        provider = self.get_provider(name)
        return provider.health_policy if provider else None

    def get_model_info(self, provider_name: str, model_name: str) -> Optional[ModelInfo]:
        """
        Retrieves the detailed configuration for a specific model of a provider.

        Args:
            provider_name: The name of the provider instance.
            model_name: The name of the model.

        Returns:
            The ModelInfo object, or None if the provider or model does not exist.
        """
        provider = self.get_provider(provider_name)
        if provider:
            return provider.models.get(model_name)
        return None

    def get_default_model_info(self, provider_name: str) -> Optional[ModelInfo]:
        """
        Retrieves the configuration for the provider's designated default model.
        This method encapsulates logic, as planned, making it a valuable improvement.

        Args:
            provider_name: The name of the provider instance.

        Returns:
            The ModelInfo object for the default model, or None if not found.
        """
        provider = self.get_provider(provider_name)
        if provider and provider.default_model:
            return provider.models.get(provider.default_model)
        return None
