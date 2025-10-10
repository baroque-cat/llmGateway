i# src/providers/impl/openai_like.py

from typing import Dict, List, Optional
import requests
import time

from src.core.models import CheckResult
from src.core.enums import ErrorReason
from src.providers.base import AIBaseProvider

# A simplified http client for demonstration purposes.
# In a real application, this would be a more robust client.
def simple_chat_request(url: str, headers: dict, model: str) -> (int, str):
    """A simple function to make a test request."""
    try:
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": "Hello"}],
            "max_tokens": 1
        }
        response = requests.post(url, headers=headers, json=payload, timeout=10)
        return response.status_code, response.text
    except requests.exceptions.Timeout:
        return 408, "Request timed out"
    except requests.exceptions.RequestException as e:
        return 500, str(e)


class OpenAILikeProvider(AIBaseProvider):
    """Provider for OpenAI-compatible APIs."""

    def _get_headers(self, token: str) -> Optional[Dict[str, str]]:
        """Constructs headers for OpenAI-like APIs."""
        if not token or not isinstance(token, str):
            return None
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }

    def check(self, token: str, **kwargs) -> CheckResult:
        """Checks the validity of an API token by making a test request."""
        start_time = time.time()
        headers = self._get_headers(token)
        if not headers:
            return CheckResult.fail(ErrorReason.INVALID_KEY, "Token is empty or invalid.")

        # Use the default_model from the provider's configuration
        model_to_test = self.config.default_model
        if not model_to_test:
            return CheckResult.fail(ErrorReason.BAD_REQUEST, "Default model for testing is not configured.")

        api_url = f"{self.config.api_base_url.rstrip('/')}/v1/chat/completions"

        status_code, response_text = simple_chat_request(api_url, headers, model_to_test)
        
        response_time = time.time() - start_time

        if status_code == 200:
            return CheckResult.success(response_time=response_time, status_code=status_code)
        elif status_code in [401, 403]:
            return CheckResult.fail(ErrorReason.INVALID_KEY, response_text, response_time, status_code)
        elif status_code == 429:
            return CheckResult.fail(ErrorReason.RATE_LIMITED, response_text, response_time, status_code)
        elif status_code >= 500:
            return CheckResult.fail(ErrorReason.SERVER_ERROR, response_text, response_time, status_code)
        else:
            return CheckResult.fail(ErrorReason.UNKNOWN, response_text, response_time, status_code)


    def inspect(self, token: str, **kwargs) -> List[str]:
        """Inspects and returns a list of available models (simplified)."""
        # This is a placeholder for a real implementation.
        # A real implementation would query the /v1/models endpoint.
        print(f"Inspecting models for provider {self.name} is not fully implemented in this example.")
        # For now, we return the models listed in the config.
        return self.config.models.get("llm", [])
