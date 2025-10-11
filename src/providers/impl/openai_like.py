# src/providers/impl/openai_like.py

from typing import Dict, List, Optional, Tuple
import requests
import time
from flask import Request

from src.core.models import CheckResult
from src.core.enums import ErrorReason
from src.providers.base import AIBaseProvider

class OpenAILikeProvider(AIBaseProvider):
    """
    Provider for OpenAI-compatible APIs (e.g., OpenAI, DeepSeek, Groq).
    This class handles the specifics of the OpenAI API format, including
    Bearer token authentication and the structure of chat completion requests.
    """

    def _get_headers(self, token: str) -> Optional[Dict[str, str]]:
        """
        Constructs the necessary authentication headers for OpenAI-like API requests.
        The standard is to use a Bearer token in the Authorization header.

        Args:
            token: The API token to be used for authentication.

        Returns:
            A dictionary of headers, or None if the token is invalid.
        """
        if not token or not isinstance(token, str):
            return None
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }

    def check(self, token: str, **kwargs) -> CheckResult:
        """
        Checks the validity of an API token by making a lightweight test request
        to the chat completions endpoint.

        Args:
            token: The API token/key to validate.
            **kwargs: Not used in this implementation but required by the interface.

        Returns:
            A CheckResult object with the validation outcome.
        """
        start_time = time.time()
        headers = self._get_headers(token)
        if not headers:
            return CheckResult.fail(ErrorReason.INVALID_KEY, "Token is empty or invalid.")

        # Use the default_model from the provider's specific configuration for the test
        model_to_test = self.config.default_model
        if not model_to_test:
            return CheckResult.fail(ErrorReason.BAD_REQUEST, "Default model for testing is not configured for this provider.")

        # Construct the API URL robustly, avoiding double slashes
        api_url = f"{self.config.api_base_url.rstrip('/')}/v1/chat/completions"

        # A minimal payload to check authentication and model access
        payload = {
            "model": model_to_test,
            "messages": [{"role": "user", "content": "Hello"}],
            "max_tokens": 1
        }
        
        try:
            response = requests.post(api_url, headers=headers, json=payload, timeout=15)
            status_code = response.status_code
            response_text = response.text
        except requests.exceptions.Timeout:
            status_code, response_text = 408, "Request timed out"
        except requests.exceptions.RequestException as e:
            status_code, response_text = 500, str(e)

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
        """
        Inspects and returns a list of available models.

        NOTE: This is a simplified placeholder implementation. A full implementation
        would make a request to the provider's `/v1/models` endpoint and parse
        the response to list all available models for the given token.
        For now, it returns the models specified in the configuration file.

        Args:
            token: The API token (not used in this simplified version).
            **kwargs: Not used in this implementation.

        Returns:
            A list of model names from the configuration.
        """
        print(f"Inspecting models for provider '{self.name}' by reading from config (full API inspection not implemented).")
        return self.config.models.get("llm", [])
    
    def proxy_request(self, token: str, request: Request) -> Tuple[requests.Response, CheckResult]:
        """
        (STUB) Proxies an incoming client request to the target API provider.
        This method will be implemented in a future step.
        """
        # This is a placeholder for the full proxy implementation.
        # It ensures the class satisfies the IProvider interface contract.
        print("TODO: Implement proxy_request for OpenAILikeProvider")
        
        # For now, return a dummy response and a server error check result
        dummy_response = requests.Response()
        dummy_response.status_code = 501 # Not Implemented
        dummy_response._content = b'{"error": "Proxy functionality not yet implemented for this provider."}'
        
        check_result = CheckResult.fail(
            ErrorReason.SERVER_ERROR,
            "Proxy functionality not implemented.",
            status_code=501
        )
        return dummy_response, check_result

