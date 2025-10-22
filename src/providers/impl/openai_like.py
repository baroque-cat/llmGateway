# src/providers/impl/openai_like.py

import json
import logging
from typing import Dict, List, Optional, Tuple

import httpx

from src.core.enums import ErrorReason
from src.core.models import CheckResult, RequestDetails
from src.providers.base import AIBaseProvider

logger = logging.getLogger(__name__)

class OpenAILikeProvider(AIBaseProvider):
    """
    Provider for OpenAI-compatible APIs (e.g., OpenAI, DeepSeek). (Async Version).
    This class serves as a versatile base for providers that follow the OpenAI API format.
    """

    async def parse_request_details(self, path: str, content: bytes) -> RequestDetails:
        """
        Parses a JSON request body to extract the model name for OpenAI-like APIs.
        This implementation ignores the URL path.
        """
        logger.debug(f"Parsing request details for provider '{self.name}'.")
        try:
            if not content:
                raise ValueError("Request body is empty.")

            json_data = json.loads(content)

            if not isinstance(json_data, dict):
                raise TypeError("Request body JSON must be an object (dictionary).")

            model_name = json_data.get("model")
            if not model_name or not isinstance(model_name, str):
                raise KeyError("Request body is missing a valid 'model' string field.")

            logger.debug(f"Successfully parsed model '{model_name}' from request body.")
            return RequestDetails(model_name=model_name)

        except json.JSONDecodeError as e:
            error_msg = f"Failed to parse request body as JSON: {e}"
            logger.warning(error_msg)
            raise ValueError(error_msg) from e
        except (KeyError, TypeError) as e:
            error_msg = f"Invalid request body structure: {e}"
            logger.warning(error_msg)
            raise ValueError(error_msg) from e


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

    def _map_status_code_to_reason(self, status_code: int) -> ErrorReason:
        """
        Maps an HTTP status code to a standardized ErrorReason enum.
        """
        if status_code in [401, 403]:
            return ErrorReason.INVALID_KEY
        if status_code == 402:
            return ErrorReason.NO_QUOTA
        if status_code == 429:
            return ErrorReason.RATE_LIMITED
        if status_code == 503:
            return ErrorReason.OVERLOADED
        if status_code >= 500:
            return ErrorReason.SERVER_ERROR
        
        return ErrorReason.UNKNOWN

    # --- REFACTORED: The method now reads endpoint and payload from the config ---
    async def check(self, client: httpx.AsyncClient, token: str, model: str) -> CheckResult:
        """
        Checks the validity of an API token by making an async, lightweight test request.
        The URL and payload for the check are now dynamically determined from the
        provider's configuration, removing hardcoded values.
        """
        logger.debug(f"Checking OpenAI-like key ending '...{token[-4:]}' for model '{model}'.")

        headers = self._get_headers(token)
        if not headers:
            return CheckResult.fail(ErrorReason.INVALID_KEY, "Token is empty or invalid.")

        # Step 1: Get model-specific configuration.
        model_info = self.config.models.get(model)
        if not model_info:
            msg = f"Configuration for model '{model}' not found in provider '{self.name}'."
            logger.error(msg)
            return CheckResult.fail(ErrorReason.BAD_REQUEST, msg)

        # Step 2: Build the URL and payload dynamically from the config.
        api_url = f"{self.config.api_base_url.rstrip('/')}{model_info.endpoint_suffix}"
        
        # Create a copy of the payload template and inject the model name.
        payload = model_info.test_payload.copy()
        payload["model"] = model
        
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
                timeout=timeout
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
            reason = self._map_status_code_to_reason(response.status_code)
            return CheckResult.fail(
                reason=reason,
                message=response.text,
                response_time=response.elapsed.total_seconds(),
                status_code=response.status_code
            )
        except httpx.RequestError as e:
            return CheckResult.fail(ErrorReason.NETWORK_ERROR, str(e), status_code=503)

    # --- REFACTORED: The method now correctly reads from the new models dictionary ---
    async def inspect(self, client: httpx.AsyncClient, token: str, **kwargs) -> List[str]:
        """
        Inspects and returns a list of available models from the configuration.
        This now correctly reads the keys from the refactored models dictionary.
        """
        logger.debug(f"Inspecting models for provider '{self.name}' by reading from config.")
        return list(self.config.models.keys())
    
    async def proxy_request(
        self, client: httpx.AsyncClient, token: str, method: str, headers: Dict, path: str, content: bytes
    ) -> Tuple[httpx.Response, CheckResult]:
        """
        Proxies the incoming request to an OpenAI-like API with streaming support.
        (No changes needed here as it relies on the path provided by the gateway)
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
                reason = self._map_status_code_to_reason(status_code)
                check_result = CheckResult.fail(reason, response_text.decode(), response_time, status_code)

        except httpx.RequestError as e:
            error_message = f"Upstream request failed: {e}"
            logger.error(error_message)
            check_result = CheckResult.fail(ErrorReason.NETWORK_ERROR, error_message, status_code=503)
            upstream_response = httpx.Response(503, content=error_message.encode())
            
        return upstream_response, check_result
