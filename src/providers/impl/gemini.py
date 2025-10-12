# src/providers/impl/gemini.py

from typing import Dict, List, Optional, Tuple
import requests
import time
import json
from flask import Request

from src.core.models import CheckResult
from src.core.enums import ErrorReason
from src.providers.base import AIBaseProvider

class GeminiProvider(AIBaseProvider):
    """Provider for Google Gemini API."""

    def _get_headers(self, token: str) -> Optional[Dict[str, str]]:
        """
        Constructs headers for Gemini API, which uses the 'x-goog-api-key' header.
        """
        if not token or not isinstance(token, str):
            return None
        return {
            "x-goog-api-key": token,
            "Content-Type": "application/json"
        }

    def check(self, token: str, **kwargs) -> CheckResult:
        """
        Checks the validity of a Gemini API token by making a lightweight test request.
        """
        start_time = time.time()
        headers = self._get_headers(token)
        if not headers:
            return CheckResult.fail(ErrorReason.INVALID_KEY, "Token is empty or invalid.")

        model_to_test = self.config.default_model
        if not model_to_test:
            return CheckResult.fail(ErrorReason.BAD_REQUEST, "Default model for testing is not configured.")

        base_url = self.config.api_base_url.rstrip('/')
        # The URL does NOT contain the key. It's in the headers.
        api_url = f"{base_url}/v1beta/models/{model_to_test}:generateContent"
        
        payload = {"contents": [{"parts": [{"text": "Hello"}]}]}

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
        elif "API_KEY_INVALID" in response_text or status_code == 400:
             return CheckResult.fail(ErrorReason.INVALID_KEY, response_text, response_time, status_code)
        elif status_code == 429:
            return CheckResult.fail(ErrorReason.RATE_LIMITED, response_text, response_time, status_code)
        elif status_code >= 500:
            return CheckResult.fail(ErrorReason.SERVER_ERROR, response_text, response_time, status_code)
        elif status_code >= 503:
            return CheckResult.fail(ErrorReason.SERVICE_OVERLOADED, response_text, response_time, status_code)
        else:
            return CheckResult.fail(ErrorReason.UNKNOWN, response_text, response_time, status_code)

    def inspect(self, token: str, **kwargs) -> List[str]:
        """
        Inspects and returns a list of available models (simplified).
        """
        # This is a placeholder for a real implementation.
        # A real implementation would query the /v1beta/models endpoint.
        print(f"Inspecting models for provider {self.name} is not fully implemented in this example.")
        # For now, we return the models listed in the config.
        return self.config.models.get("llm", [])

    def proxy_request(self, token: str, request: Request) -> Tuple[requests.Response, CheckResult]:
        """
        Proxies the incoming request to the Gemini API.
        """
        start_time = time.time()
        
        # 1. Build the upstream URL from the client's path.
        base_url = self.config.api_base_url.rstrip('/')
        upstream_url = f"{base_url}/{request.path.lstrip('/')}"
        
        # 2. Prepare headers. This will remove client auth and add provider auth.
        headers = self._prepare_proxy_headers(token, request.headers)
        
        # 3. Execute the request to the upstream provider, with streaming enabled.
        try:
            upstream_response = requests.request(
                method=request.method,
                url=upstream_url,
                headers=headers,
                data=request.get_data(),
                stream=True,  # Crucial for LLM streaming
                timeout=300 # A reasonable timeout for LLM requests
            )
            
            response_time = time.time() - start_time
            status_code = upstream_response.status_code
            response_text = "" # We don't read the body for successful streams
            
            # 4. Create a CheckResult based on the response status.
            if upstream_response.ok:
                check_result = CheckResult.success(
                    response_time=response_time, status_code=status_code
                )
            else:
                # If the request fails, we read the body to get the error message.
                response_text = upstream_response.text
                if status_code in [401, 403, 400]:
                    reason = ErrorReason.INVALID_KEY
                elif status_code == 429:
                    reason = ErrorReason.RATE_LIMITED
                elif status_code >= 500:
                    reason = ErrorReason.SERVER_ERROR
                elif status_code == 503: 
                    reason = ErrorReason.OVERLOADED
                else:
                    reason = ErrorReason.UNKNOWN

                check_result = CheckResult.fail(
                    reason, response_text, response_time, status_code
                )

        except requests.exceptions.RequestException as e:
            # Handle network-level errors (e.g., timeout, connection error)
            response_time = time.time() - start_time
            upstream_response = requests.Response() # Create a dummy response object
            upstream_response.status_code = 503 
            upstream_response.reason = str(e)
            check_result = CheckResult.fail(
                ErrorReason.NETWORK_ERROR, str(e), response_time, 503
            )
            
        return upstream_response, check_result

