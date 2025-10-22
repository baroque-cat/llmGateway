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
        
        # This new structure allows a single provider to handle different
        # model types (text, image, etc.) by reading its configuration.
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
            "imagen-4.0-generate-001": {
                # A different suffix is used for image generation models.
                "endpoint_suffix": ":predict",
                # The payload structure is also different for image models.
                "test_payload": {
                    "instances": [{"prompt": "test image"}]
                }
            }
        },
    },
    
    "deepseek": {
        "api_base_url": "https://api.deepseek.com",
        "default_model": "deepseek-chat",
        
        # For OpenAI-like APIs, the endpoint is often the same for all chat models.
        "models": {
            "deepseek-chat": {
                # The full path appended to the base URL.
                "endpoint_suffix": "/chat/completions",
                # Note: The 'model' field is intentionally omitted.
                # The provider code is responsible for injecting the correct
                # model name into this payload before sending the request.
                "test_payload": {
                    "messages": [{"role": "user", "content": "Hello"}],
                    "max_tokens": 1,
                }
            },
            "deepseek-reasoner": {
                "endpoint_suffix": "/chat/completions",
                "test_payload": {
                    "messages": [{"role": "user", "content": "Hello"}],
                    "max_tokens": 1,
                }
            }
        },
    },
}
