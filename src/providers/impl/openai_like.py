# src/providers/impl/openai_like.py

from typing import Dict, List, Optional, Tuple
import requests
import time
import logging
from flask import Request

from src.core.models import CheckResult
from src.core.enums import ErrorReason
from src.providers.base import AIBaseProvider

logger = logging.getLogger(__name__)

class OpenAILikeProvider(AIBaseProvider):
    """
    Provider for OpenAI-compatible APIs (e.g., OpenAI, DeepSeek, Groq).
    """

    def _get_headers(self, token: str) -> Optional[Dict[str, str]]:
        """
        Constructs the necessary authentication headers for OpenAI-like API requests.
        """
        if not token or not isinstance(token, str):
            return None
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }

    def check(self, token: str, model: str, proxy: Optional[str] = None) -> CheckResult:
        """
        Checks the validity of an API token by making a lightweight test request.
        
        Args:
            token: The API token to validate.
            model: The specific model name to use for the check.
            proxy: (Optional) The proxy URL to use for the request.
        """
        start_time = time.time()
        
        log_proxy_msg = f"via proxy '{proxy}'" if proxy else "directly"
        logger.debug(f"Checking OpenAI-like key ending '...{token[-4:]}' for model '{model}' {log_proxy_msg}.")

        headers = self._get_headers(token)
        if not headers:
            return CheckResult.fail(ErrorReason.INVALID_KEY, "Token is empty or invalid.")

        if not model:
            return CheckResult.fail(ErrorReason.BAD_REQUEST, "Model for testing is not specified.")

        api_url = f"{self.config.api_base_url.rstrip('/')}/v1/chat/completions"

        payload = {
            "model": model,
            "messages": [{"role": "user", "content": "Hello"}],
            "max_tokens": 1
        }
        
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
        Inspects and returns a list of available models from configuration.
        """
        logger.debug(f"Inspecting models for provider '{self.name}' by reading from config.")
        return self.config.models.get("llm", [])
    
    def proxy_request(self, token: str, request: Request) -> Tuple[requests.Response, CheckResult]:
        """
        (STUB) Proxies an incoming client request to the target API provider.
        """
        logger.warning("proxy_request for OpenAILikeProvider is not yet implemented.")
        
        dummy_response = requests.Response()
        dummy_response.status_code = 501
        dummy_response._content = b'{"error": "Proxy functionality not yet implemented for this provider."}'
        
        check_result = CheckResult.fail(
            ErrorReason.SERVER_ERROR,
            "Proxy functionality not implemented.",
            status_code=501
        )
        return dummy_response, check_result
