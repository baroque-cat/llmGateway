# src/config/loader.py

import os
import yaml
from src.config.schemas import Config, ProviderConfig
from src.config.defaults import get_default_config

def load_config(path: str = "config/providers.yaml") -> Config:
    """
    Loads configuration from a YAML file.
    If the file does not exist, it creates a default one.
    It parses the raw data into structured Config objects.
    
    Args:
        path: The path to the YAML configuration file.

    Returns:
        A populated and validated Config object.
    """
    if not os.path.exists(path):
        print(f"Configuration file not found at '{path}'. Creating a default one.")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            yaml.dump(get_default_config(), f, default_flow_style=False, sort_keys=False)

    with open(path, 'r', encoding='utf-8') as f:
        raw_config = yaml.safe_load(f)

    app_config = Config()

    for name, provider_data in raw_config.get('providers', {}).items():
        provider_conf = ProviderConfig(
            provider_type=provider_data.get('provider_type', ''),
            enabled=provider_data.get('enabled', False),
            keys_path=provider_data.get('keys_path', ''),
            api_base_url=provider_data.get('api_base_url', ''),
            default_model=provider_data.get('default_model', ''),
            models=provider_data.get('models', {}),
            use_proxy_list=provider_data.get('use_proxy_list')
        )
        app_config.providers[name] = provider_conf

    # Simple validation
    for name, conf in app_config.providers.items():
        if conf.enabled:
            if not conf.provider_type:
                raise ValueError(f"Provider '{name}' is enabled but 'provider_type' is not set.")
            if not conf.keys_path:
                raise ValueError(f"Provider '{name}' is enabled but 'keys_path' is not set.")
            if not conf.default_model:
                raise ValueError(f"Provider '{name}' is enabled but 'default_model' is not set.")

    return app_config

