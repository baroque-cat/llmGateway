# src/providers/impl/gemini.py

from typing import Dict, List, Optional
import requests
import time

from src.core.models import CheckResult
from src.core.enums import ErrorReason
from src.providers.base import AIBaseProvider

# A simplified http client for demonstration purposes.
def simple_gemini_request(url: str, headers: dict) -> (int, str):
    """A simple function to make a test request to Gemini."""
    try:
        payload = {"contents": [{"parts": [{"text": "Hello"}]}]}
        response = requests.post(url, headers=headers, json=payload, timeout=10)
        return response.status_code, response.text
    except requests.exceptions.Timeout:
        return 408, "Request timed out"
    except requests.exceptions.RequestException as e:
        return 500, str(e)


class GeminiProvider(AIBaseProvider):
    """Provider for Google Gemini API."""

    def _get_headers(self, token: str) -> Optional[Dict[str, str]]:
        """Gemini does not use Authorization headers, key is in URL."""
        return {"Content-Type": "application/json"}

    def check(self, token: str, **kwargs) -> CheckResult:
        """Checks the validity of a Gemini API token."""
        start_time = time.time()
        if not token or not isinstance(token, str):
            return CheckResult.fail(ErrorReason.INVALID_KEY, "Token is empty or invalid.")

        # Use the default_model from the provider's configuration
        model_to_test = self.config.default_model
        if not model_to_test:
            return CheckResult.fail(ErrorReason.BAD_REQUEST, "Default model for testing is not configured.")

        base_url = self.config.api_base_url.rstrip('/')
        api_url = f"{base_url}/v1beta/models/{model_to_test}:generateContent?key={token}"
        
        headers = self._get_headers(token)
        
        status_code, response_text = simple_gemini_request(api_url, headers)
        
        response_time = time.time() - start_time

        if status_code == 200:
            return CheckResult.success(response_time=response_time, status_code=status_code)
        elif "API_KEY_INVALID" in response_text or status_code == 400:
             return CheckResult.fail(ErrorReason.INVALID_KEY, response_text, response_time, status_code)
        elif status_code == 429:
            return CheckResult.fail(ErrorReason.NO_QUOTA, response_text, response_time, status_code)
        elif status_code >= 500:
            return CheckResult.fail(ErrorReason.SERVER_ERROR, response_text, response_time, status_code)
        else:
            return CheckResult.fail(ErrorReason.UNKNOWN, response_text, response_time, status_code)

    def inspect(self, token: str, **kwargs) -> List[str]:
        """Inspects and returns a list of available models (simplified)."""
        # This is a placeholder for a real implementation.
        # A real implementation would query the /v1beta/models endpoint.
        print(f"Inspecting models for provider {self.name} is not fully implemented in this example.")
        # For now, we return the models listed in the config.
        return self.config.models.get("llm", [])
