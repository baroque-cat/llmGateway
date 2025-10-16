# src/providers/impl/openai_like.py

import logging
from typing import Dict, List, Optional, Tuple

import httpx

from src.core.enums import ErrorReason
from src.core.models import CheckResult
from src.providers.base import AIBaseProvider

logger = logging.getLogger(__name__)

class OpenAILikeProvider(AIBaseProvider):
    """
    Provider for OpenAI-compatible APIs (e.g., OpenAI, DeepSeek) (Async Version).
    """

    def _get_headers(self, token: str) -> Optional[Dict[str, str]]:
        """
        Constructs the necessary authentication headers for OpenAI-like API requests.
        """
        if not token or not isinstance(token, str):
            return None
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

    async def check(self, client: httpx.AsyncClient, token: str, model: str, proxy: Optional[str] = None) -> CheckResult:
        """
        Checks the validity of an API token by making an async, lightweight test request.
        """
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
            "max_tokens": 1,
        }

        timeout_config = self.config.timeouts
        timeout = httpx.Timeout(
            connect=timeout_config.connect,
            read=timeout_config.read,
            write=timeout_config.write,
            pool=timeout_config.pool
        )
        
        try:
            response = await client.post(
                api_url,
                headers=headers,
                json=payload,
                timeout=timeout,
                proxies=proxy
            )
            response.raise_for_status()
            
            return CheckResult.success(response_time=response.elapsed.total_seconds(), status_code=response.status_code)

        except httpx.TimeoutException:
            return CheckResult.fail(ErrorReason.TIMEOUT, "Request timed out", timeout.read, 408)
        except httpx.ProxyError as e:
            return CheckResult.fail(ErrorReason.NETWORK_ERROR, f"Proxy error: {e}", status_code=503)
        except httpx.ConnectError as e:
            return CheckResult.fail(ErrorReason.NETWORK_ERROR, f"Connection error: {e}", status_code=503)
        except httpx.HTTPStatusError as e:
            response = e.response
            status_code = response.status_code
            response_text = response.text
            response_time = response.elapsed.total_seconds()

            if status_code in [401, 403]:
                return CheckResult.fail(ErrorReason.INVALID_KEY, response_text, response_time, status_code)
            elif status_code == 429:
                return CheckResult.fail(ErrorReason.RATE_LIMITED, response_text, response_time, status_code)
            elif status_code >= 500:
                return CheckResult.fail(ErrorReason.SERVER_ERROR, response_text, response_time, status_code)
            else:
                return CheckResult.fail(ErrorReason.UNKNOWN, response_text, response_time, status_code)
        except httpx.RequestError as e:
            return CheckResult.fail(ErrorReason.NETWORK_ERROR, str(e), status_code=503)

    async def inspect(self, client: httpx.AsyncClient, token: str, **kwargs) -> List[str]:
        """
        Inspects and returns a list of available models from configuration.
        """
        logger.debug(f"Inspecting models for provider '{self.name}' by reading from config.")
        return self.config.models.get("llm", [])
    
    async def proxy_request(
        self, client: httpx.AsyncClient, token: str, method: str, headers: Dict, path: str, content: bytes
    ) -> Tuple[httpx.Response, CheckResult]:
        """
        Proxies the incoming request to an OpenAI-like API with streaming support.
        """
        base_url = self.config.api_base_url.rstrip('/')
        upstream_url = f"{base_url}/{path.lstrip('/')}"
        
        proxy_headers = self._prepare_proxy_headers(token, headers)
        
        timeout_config = self.config.timeouts
        timeout = httpx.Timeout(
            connect=timeout_config.connect,
            read=timeout_config.read,
            write=timeout_config.write,
            pool=timeout_config.pool
        )
        
        try:
            upstream_request = client.build_request(
                method=method,
                url=upstream_url,
                headers=proxy_headers,
                content=content,
                timeout=timeout,
            )
            upstream_response = await client.send(upstream_request, stream=True)
            
            status_code = upstream_response.status_code
            response_time = upstream_response.elapsed.total_seconds()
            
            if upstream_response.is_success:
                check_result = CheckResult.success(response_time=response_time, status_code=status_code)
            else:
                response_text = await upstream_response.aread()
                if status_code in [401, 403]:
                    reason = ErrorReason.INVALID_KEY
                elif status_code == 429:
                    reason = ErrorReason.RATE_LIMITED
                elif status_code >= 500:
                    reason = ErrorReason.SERVER_ERROR
                else:
                    reason = ErrorReason.UNKNOWN

                check_result = CheckResult.fail(reason, response_text.decode(), response_time, status_code)

        except httpx.RequestError as e:
            error_message = f"Upstream request failed: {e}"
            logger.error(error_message)
            check_result = CheckResult.fail(ErrorReason.NETWORK_ERROR, error_message, status_code=503)
            upstream_response = httpx.Response(503, content=error_message.encode())
            
        return upstream_response, check_result
