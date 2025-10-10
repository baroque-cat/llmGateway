# src/config/defaults.py

from typing import Any, Dict

def get_default_config() -> Dict[str, Any]:
    """
    Returns the default configuration structure as a dictionary.
    This serves as a template for generating the initial providers.yaml file.
    """
    return {
        "providers": {
            "gemini": {
                "enabled": True,
                "keys_path": "keys/gemini/",
                "api_base_url": "https://generativelanguage.googleapis.com",
                "default_model": "gemini-2.5-flash",
                "models": {
                    "llm": [
                        "gemini-2.5-pro",
                        "gemini-2.5-flash"
                    ]
                }
            },
        }
    }
