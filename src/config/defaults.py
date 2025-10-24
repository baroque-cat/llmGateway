# src/config/defaults.py

from typing import Any, Dict

def get_default_config() -> Dict[str, Any]:
    """
    Returns the default configuration structure as a dictionary.
    This serves as a template for generating the initial providers.yaml file.
    The structure is updated to reflect the new multimodal model configuration.
    """
    return {
        # --- GLOBAL SETTINGS ---
        "debug": False,

        # --- WORKER SETTINGS ---
        "worker": {
            # Concurrency limit for the background worker's probes.
            "max_concurrent_providers": 10,
        },
        
        "database": {
            "host": "localhost",
            "port": 5433,
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
        # This section serves as a generic template for any new provider instance.
        "providers": {
            "llm_provider_default": {
                # This will be overridden by the template (e.g., 'gemini', 'deepseek').
                "provider_type": "placeholder_type", 
                "enabled": True,
                # This path is customized by the config manager.
                "keys_path": "keys/llm_provider_default/",
                
                "api_base_url": "https://api.example.com/v1",
                
                "models": {},
                

                "access_control": {
                    "gateway_access_token": "${LLM_PROVIDER_DEFAULT_TOKEN}",
                },

                # Policy for the background worker's health checks.
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
                    # This path is customized by the config manager.
                    "pool_list_path": "proxies/llm_provider_default/",
                },
                
                "timeouts": {
                    "connect": 5.0,
                    "read": 20.0,
                    "write": 10.0,
                    "pool": 5.0,
                },

                # Policies applied only by the API Gateway during request processing.
                "gateway_policy": {
                    # Retry policies for failed requests.
                    "retry": {
                        "enabled": False,
                        "on_key_error": {
                            "attempts": 3,
                        },
                        "on_server_error": {
                            "attempts": 5,
                            "backoff_sec": 0.5,
                            "backoff_factor": 2.0,
                        },
                    },
                    # Circuit breaker to protect against cascading failures.
                    "circuit_breaker": {
                        "enabled": False,
                        "mode": "auto_recovery", # manual_reset
                        "failure_threshold": 20,
                        "jitter_sec": 5,
                        "backoff": {
                            "base_duration_sec": 60,
                            "max_duration_sec": 3600,
                            "factor": 2.0,
                        },
                    },
                },
            },
        },
    }

