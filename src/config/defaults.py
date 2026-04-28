#!/usr/bin/env python3

from typing import Any


def get_default_config() -> dict[str, Any]:
    """
    Returns the default configuration structure as a dictionary.
    This serves as a template for generating the initial providers.yaml file.
    The structure is updated to reflect the new multimodal model configuration.
    """
    return {
        # --- LOGGING SETTINGS ---
        "logging": {
            "level": "INFO",
        },
        # The metrics accessor key belongs here in the future when added.
        # --- GATEWAY SETTINGS ---
        "gateway": {
            "host": "0.0.0.0",
            "port": 55300,
            "workers": 4,
        },
        # --- WORKER SETTINGS ---
        "worker": {
            # Concurrency limit for the background worker's probes.
            "max_concurrent_providers": 10,
        },
        # --- DATABASE SETTINGS ---
        "database": {
            "host": "localhost",
            "port": 5432,
            "user": "llm_gateway",
            # This value is expected to be loaded from an environment variable.
            # Create a .env file in the project root with the line:
            # DB_PASSWORD="your_super_secret_password"
            "password": "${DB_PASSWORD}",
            "dbname": "llmgateway",
            # Connection pool settings for asyncpg.
            "pool": {
                "min_size": 1,
                "max_size": 15,
            },
            # Retry policy for transient database errors
            "retry": {
                "max_attempts": 3,
                "base_delay_sec": 1.0,
                "backoff_factor": 2.0,
                "jitter": True,
            },
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
                "proxy_config": {
                    "mode": "none",
                    "static_url": None,
                    # This path is customized by the config manager.
                    "pool_list_path": "proxies/llm_provider_default/",
                },
                "timeouts": {
                    "connect": 15.0,
                    "read": 300.0,
                    "write": 35.0,
                    "pool": 35.0,
                },
                # Policy for the background worker's health checks.
                # REFACTORED: This section now perfectly matches the updated HealthPolicyConfig schema.
                "worker_health_policy": {
                    # Intervals in Minutes
                    "on_server_error_min": 30,
                    "on_overload_min": 30,
                    # Intervals in Hours
                    "on_other_error_hr": 1,
                    "on_success_hr": 24,
                    "on_rate_limit_hr": 1,
                    "on_no_quota_hr": 6,
                    # Intervals in Days
                    "on_invalid_key_days": 10,
                    "on_no_access_days": 10,
                    # Quarantine Policies
                    "quarantine_after_days": 30,
                    "quarantine_recheck_interval_days": 10,
                    "stop_checking_after_days": 90,
                    # Downtime Amnesty Policy
                    "amnesty_threshold_days": 2.0,
                    # Batching Configuration
                    # Adaptive Batching — self-tuning controller (all optional)
                    "adaptive_batching": {
                        # Start values (moved from HealthPolicyConfig)
                        "start_batch_size": 10,
                        "start_batch_delay_sec": 30.0,
                        # Boundaries
                        "min_batch_size": 5,
                        "max_batch_size": 50,
                        "min_batch_delay_sec": 3.0,
                        "max_batch_delay_sec": 120.0,
                        # Steps
                        "batch_size_step": 5,
                        "delay_step_sec": 2.0,
                        "rate_limit_divisor": 2,
                        "rate_limit_delay_multiplier": 2.0,
                        "recovery_threshold": 5,
                        "recovery_step_multiplier": 2.0,
                        "failure_rate_threshold": 0.3,
                    },
                    "task_timeout_sec": 900,
                    # Verification Loop Configuration
                    "verification_attempts": 3,
                    "verification_delay_sec": 65,
                    # Fast Status Mapping for worker health checks
                    "fast_status_mapping": {},
                },
                # Policies applied only by the API Gateway during request processing.
                "gateway_policy": {
                    # Controls whether streaming is enabled for this provider instance.
                    # - "auto": Streaming is enabled when technically possible (current behavior).
                    # - "disabled": Streaming is explicitly disabled in both directions (request and response).
                    "streaming_mode": "auto",
                    # Controls the debug logging mode for this provider instance.
                    # - "disabled": No additional debug logging.
                    # - "no_content": Log all request/response metadata and parameters,
                    #                 but redact content fields (messages, thinking, generated text).
                    # - "full_body": Log full request and response including all bodies,
                    #                with sensitive fields (api_key, token) redacted.
                    "debug_mode": "disabled",
                    # Configuration for parsing error responses to refine error classification
                    # This enables distinguishing between different error types with the same HTTP status code
                    "error_parsing": {"enabled": False, "rules": []},
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
                        "mode": "auto_recovery",  # manual_reset
                        "failure_threshold": 20,
                        "jitter_sec": 5,
                        "backoff": {
                            "base_duration_sec": 60,
                            "max_duration_sec": 3600,
                            "factor": 2.0,
                        },
                    },
                    # Mapping of HTTP status codes to ErrorReason strings for fast, body-less error handling.
                    # When a status code matches an entry here, the gateway will IMMEDIATELY fail the request
                    # with the mapped reason without reading the response body.
                    "fast_status_mapping": {},
                },
            },
        },
    }
