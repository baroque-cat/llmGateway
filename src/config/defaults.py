# src/config/defaults.py

from typing import Any, Dict

def get_default_config() -> Dict[str, Any]:
    """
    Returns the default configuration structure as a dictionary.
    This serves as a template for generating the initial providers.yaml file.
    """
    return {
        "providers": {
            "gemini_default": {
                "provider_type": "gemini",
                "enabled": True,
                "keys_path": "keys/gemini/",
                "api_base_url": "https://generativelanguage.googleapis.com",
                "default_model": "gemini-2.5-flash",
                "models": {
                    "llm": [
                        "gemini-2.5-flash",
                        "gemini-2.5-pro"
                    ]
                }
                "access_control": {
                    "gateway_access_token": "gp-changeme-xxxxxxxxxxxxxxxxxxxx"
                },

                "health_policy": {
                    "on_success_hr": 2,
                    "on_overload_min": 60,
                    "on_no_quota_hr": 24,
                    "on_rate_limit_min": 180,
                    "on_server_error_min": 10,
                    "on_invalid_key_days": 10,
                    "on_other_error_hr": 1
                    "batch_size": 30,
                    "batch_delay_sec": 15
                },

                "proxy_config": {
                    "mode": "none",
                    "static_url": None,
                    "pool_list_path": "proxies/gemini/"
                }
            },
        }
    }
