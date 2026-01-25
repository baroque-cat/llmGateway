# src/config/provider_templates.py

"""
Centralized Provider Type Templates.

This module contains a single dictionary that maps a provider_type string
to its unique, non-generic settings. This new structure is designed to be
multimodal and config-driven, removing hardcoded values from the provider code.

Key changes:
- The `models` field is now a dictionary where each key is a model name.
- Each model has its own `endpoint_suffix` and `test_payload`.
- The 'llm' sub-section within `models` has been removed for a flatter, more
  direct structure.
"""

PROVIDER_TYPE_DEFAULTS = {
    "gemini": {
        "api_base_url": "https://generativelanguage.googleapis.com",
        "default_model": "gemini-2.5-flash",
        "shared_key_status": False,

        "models": {
            "gemini-2.5-flash": {
                # The suffix appended to the model-specific URL for text generation.
                "endpoint_suffix": ":generateContent",
                # The minimal payload required for a successful health check.
                "test_payload": {
                    "contents": [{"parts": [{"text": "Hello"}]}]
                }
            },
            "gemini-2.5-pro": {
                "endpoint_suffix": ":generateContent",
                "test_payload": {
                    "contents": [{"parts": [{"text": "Hello"}]}]
                }
            },
            "imagen-3.0-generate-002": {
                # A different suffix is used for image generation models.
                "endpoint_suffix": ":predict",
                # The payload structure is also different for image models.
                "test_payload": {
                    "instances": [{"prompt": "test image"}]
                }
            }
        },
    },
    
    "openai_like": {
        # Placeholder suggesting the format, forcing user input
        "api_base_url": "https://api.provider-domain.com/v1",
        "default_model": "your-model-name",
        "shared_key_status": False,

        "models": {
            "your-model-name": {
                # Standard suffix for most OpenAI-compatible APIs
                "endpoint_suffix": "/chat/completions",
                # Minimal payload for health checks
                "test_payload": {
                    "messages": [{"role": "user", "content": "Hi"}],
                    "max_tokens": 1
                }
            }
        },
    },
}
