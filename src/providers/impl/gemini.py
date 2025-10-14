# src/providers/impl/gemini.py

from typing import Dict, List, Optional, Tuple
import requests
import time
import logging
from flask import Request

from src.core.models import CheckResult
from src.core.enums import ErrorReason
from src.providers.base import AIBaseProvider

logger = logging.getLogger(__name__)

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

    def check(self, token: str, model: str, proxy: Optional[str] = None) -> CheckResult:
        """
        Checks the validity of a Gemini API token by making a lightweight test request.
        
        Args:
            token: The API token to validate.
            model: The specific model name to use for the check.
            proxy: (Optional) The proxy URL to use for the request.
        """
        start_time = time.time()
        
        log_proxy_msg = f"via proxy '{proxy}'" if proxy else "directly"
        logger.debug(f"Checking Gemini key ending '...{token[-4:]}' for model '{model}' {log_proxy_msg}.")

        headers = self._get_headers(token)
        if not headers:
            return CheckResult.fail(ErrorReason.INVALID_KEY, "Token is empty or invalid.")

        if not model:
            return CheckResult.fail(ErrorReason.BAD_REQUEST, "Model for testing is not specified.")

        base_url = self.config.api_base_url.rstrip('/')
        api_url = f"{base_url}/v1beta/models/{model}:generateContent"
        
        payload = {"contents": [{"parts": [{"text": "Hello"}]}]}
        
        # Prepare proxies dictionary for the requests library
        proxies_dict = {"http": proxy, "https": proxy} if proxy else None

        try:
            response = requests.post(
                api_url, 
                headers=headers, 
                json=payload, 
                timeout=15, 
                proxies=proxies_dict
            )
            status_code = response.status_code
            response_text = response.text
        except requests.exceptions.Timeout:
            return CheckResult.fail(ErrorReason.TIMEOUT, "Request timed out", time.time() - start_time, 408)
        except requests.exceptions.ProxyError as e:
            return CheckResult.fail(ErrorReason.NETWORK_ERROR, f"Proxy error: {e}", time.time() - start_time, 503)
        except requests.exceptions.RequestException as e:
            return CheckResult.fail(ErrorReason.NETWORK_ERROR, str(e), time.time() - start_time, 503)

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
            return CheckResult.fail(ErrorReason.OVERLOADED, response_text, response_time, status_code)
        else:
            return CheckResult.fail(ErrorReason.UNKNOWN, response_text, response_time, status_code)

    def inspect(self, token: str, **kwargs) -> List[str]:
        """
        Inspects and returns a list of available models (simplified).
        """
        logger.debug(f"Inspecting models for provider {self.name} (not fully implemented).")
        return self.config.models.get("llm", [])

    def proxy_request(self, token: str, request: Request) -> Tuple[requests.Response, CheckResult]:
        """
        Proxies the incoming request to the Gemini API.
        """
        # This implementation remains unchanged as it was not part of the task.
        # However, for full functionality, proxy logic would need to be added here as well.
        start_time = time.time()
        
        base_url = self.config.api_base_url.rstrip('/')
        upstream_url = f"{base_url}/{request.path.lstrip('/')}"
        
        headers = self._prepare_proxy_headers(token, request.headers)
        
        try:
            upstream_response = requests.request(
                method=request.method,
                url=upstream_url,
                headers=headers,
                data=request.get_data(),
                stream=True,
                timeout=300
            )
            
            response_time = time.time() - start_time
            status_code = upstream_response.status_code
            response_text = ""
            
            if upstream_response.ok:
                check_result = CheckResult.success(response_time=response_time, status_code=status_code)
            else:
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

                check_result = CheckResult.fail(reason, response_text, response_time, status_code)

        except requests.exceptions.RequestException as e:
            response_time = time.time() - start_time
            upstream_response = requests.Response()
            upstream_response.status_code = 503
            upstream_response.reason = str(e)
            check_result = CheckResult.fail(ErrorReason.NETWORK_ERROR, str(e), response_time, 503)
            
        return upstream_response, check_result
