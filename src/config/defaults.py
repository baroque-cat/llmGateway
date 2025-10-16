# src/config/defaults.py

from typing import Any, Dict

def get_default_config() -> Dict[str, Any]:
    """
    Returns the default configuration structure as a dictionary.
    This serves as a template for generating the initial providers.yaml file.
    """
    return {
        # --- GLOBAL SETTINGS ---
        "debug": False,
        
        "database": {
            "host": "localhost",
            "port": 5432,
            "user": "llm_gateway",
            # This value is expected to be loaded from an environment variable.
            # Create a .env file in the project root with the line:
            # DB_PASSWORD="your_super_secret_password"
            "password": "${DB_PASSWORD}",
            "dbname": "llmgateway",
        },

        "logging": {
            "summary_log_path": "logs/summary/",
            "summary_interval_min": 60,
            "summary_log_max_size_mb": 5,
            "summary_log_backup_count": 3,
        },
        
        # --- PROVIDER-SPECIFIC SETTINGS ---
        "providers": {
            "gemini_default": {
                "provider_type": "gemini",
                "enabled": True,
                "keys_path": "keys/gemini/",
                "api_base_url": "https://generativelanguage.googleapis.com",
                "default_model": "gemini-2.5-flash",
                
                "shared_key_status": False,
                
                "models": {
                    "llm": [
                        "gemini-2.5-flash",
                        "gemini-2.5-pro",
                    ],
                },
                "access_control": {
                    # This is the authentication token your client application will use
                    # to access the gateway for this specific provider.
                    # It's recommended to load it from a .env file:
                    # GEMINI_DEFAULT_TOKEN="gp-..."
                    "gateway_access_token": "${GEMINI_DEFAULT_TOKEN}",
                },

                "health_policy": {
                    "on_success_hr": 2,
                    "on_overload_min": 60,
                    "on_no_quota_hr": 24,
                    "on_rate_limit_min": 180,
                    "on_server_error_min": 30,
                    "on_invalid_key_days": 10,
                    "on_other_error_hr": 1,
                    "batch_size": 30,
                    "batch_delay_sec": 15,
                },

                "proxy_config": {
                    "mode": "none",
                    "static_url": None,
                    "pool_list_path": "proxies/gemini/",
                },

                # --- NEW SECTION ---
                "timeouts": {
                    "connect": 5.0,
                    "read": 20.0,
                    "write": 10.0,
                    "pool": 5.0,
                },
            },
        },
    }
