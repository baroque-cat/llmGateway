# src/config/provider_templates.py

"""
Centralized Provider Type Templates.

This module contains a single dictionary that maps a provider_type string
to its unique, non-generic settings. When the ConfigManager creates a new
provider instance, it uses a generic template from defaults.py and then
overwrites the specific fields using the data from this file.

To add support for a new provider type, you only need to add a new
entry to the PROVIDER_TYPE_DEFAULTS dictionary.
"""

PROVIDER_TYPE_DEFAULTS = {
    "gemini": {
        "api_base_url": "https://generativelanguage.googleapis.com",
        "default_model": "gemini-2.5-flash",
        "models": {
            "llm": [
                "gemini-2.5-flash",
                "gemini-2.5-pro",
            ],
        },
    },
    "deepseek": {
        "api_base_url": "https://api.deepseek.com",
        "default_model": "deepseek-chat",
        "models": {
            "llm": [
                "deepseek-chat",
                "deepseek-reasoner",
            ],
        },
    },
}
