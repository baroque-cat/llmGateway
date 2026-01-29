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

    # --- Implementation of the error parsing contract from AIBaseProvider ---
    async def _parse_proxy_error(self, response: httpx.Response) -> CheckResult:
        """
        Parses a failed OpenAI-like API response into a standardized CheckResult.

        This method implements the safe-access pattern required by httpx:
        1. Read the response body first.
        2. THEN, access properties like .elapsed.
        This fixes the latent RuntimeError for this provider type.
        
        Now enhanced with error parsing rules from configuration.
        """
        status_code = response.status_code
        
        # 1. Read body first (required for safe .elapsed access)
        response_bytes = await response.aread()
        response_text = response_bytes.decode(errors='ignore')

        # 2. Access .elapsed now that it's safe.
        response_time = response.elapsed.total_seconds()
        
        # 3. Get default reason based on status code
        default_reason = self._map_status_code_to_reason(status_code)
        
        # 4. Refine reason using error parsing rules (if configured)
        # Pass the already-read body to avoid re-reading
        refined_reason = await self._refine_error_reason(
            response=response,
            default_reason=default_reason,
            body_bytes=response_bytes
        )
        
        return CheckResult.fail(refined_reason, response_text, response_time, status_code)

    async def parse_request_details(self, path: str, content: bytes) -> RequestDetails:
        """
        Parses a JSON request body to extract the model name for OpenAI-like APIs.
        This implementation ignores the URL path.
        
        Args:
            path: The URL path of the original request (ignored).
            content: The raw byte content (body) of the original request.
        
        Returns:
            A RequestDetails object with the parsed model name.
        
        Raises:
            ValueError: If the request body is empty, not valid JSON, or is missing
                        the required 'model' field.
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
        if status_code == 400:
            return ErrorReason.BAD_REQUEST
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

    async def check(self, client: httpx.AsyncClient, token: str, **kwargs) -> CheckResult:
        """
        Checks the validity of an API token by making an async, lightweight test request.
        The URL and payload for the check are now dynamically determined from the
        provider's configuration, removing hardcoded values.
        
        Args:
            client: The httpx.AsyncClient to use for the request.
            token: The API token to validate.
            **kwargs: Additional keyword arguments. Expected to contain 'model' key.
            
        Returns:
            A CheckResult indicating the success or failure of the check.
        """
        model = kwargs.get('model')
        if not model:
            return CheckResult.fail(ErrorReason.BAD_REQUEST, "Missing 'model' parameter in check method.")
        logger.debug(f"Checking OpenAI-like key ending '...{token[-4:]}' for model '{model}'.")

        headers = self._get_headers(token)
        if not headers:
            return CheckResult.fail(ErrorReason.INVALID_KEY, "Token is empty or invalid.")

        model_info = self.config.models.get(model)
        if not model_info:
            msg = f"Configuration for model '{model}' not found in provider '{self.name}'."
            logger.error(msg)
            return CheckResult.fail(ErrorReason.BAD_REQUEST, msg)

        api_url = f"{self.config.api_base_url.rstrip('/')}{model_info.endpoint_suffix}"
        
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
            status_code = response.status_code
            
            # Special handling for worker: 400 errors in check() likely indicate invalid key
            # since the request format is predetermined and correct
            if status_code == 400:
                reason = ErrorReason.INVALID_KEY
                logger.debug(f"Worker check received 400 error, treating as {reason.value} for key validation")
            else:
                reason = self._map_status_code_to_reason(status_code)
            
            return CheckResult.fail(
                reason=reason,
                message=response.text,
                response_time=response.elapsed.total_seconds(),
                status_code=status_code
            )
        except httpx.RequestError as e:
            return CheckResult.fail(ErrorReason.NETWORK_ERROR, str(e), status_code=503)

    async def inspect(self, client: httpx.AsyncClient, token: str, **kwargs) -> List[str]:
        """
        Inspects and returns a list of available models from the configuration.
        This now correctly reads the keys from the refactored models dictionary.
        """
        logger.debug(f"Inspecting models for provider '{self.name}' by reading from config.")
        return list(self.config.models.keys())
    
    # --- REFACTORED: Now uses the centralized helper method from AIBaseProvider ---
    async def proxy_request(
        self, client: httpx.AsyncClient, token: str, method: str, headers: Dict, path: str, query_params: str, content: bytes
    ) -> Tuple[httpx.Response, CheckResult]:
        """
        Proxies the incoming request to an OpenAI-like API.
        
        This method is now a thin wrapper that constructs the request and then
        delegates the sending and response parsing to the robust `_send_proxy_request`
        method in the base class.
        """
        # 1. Construct the full upstream URL.
        base_url = self.config.api_base_url.rstrip('/')
        upstream_url = f"{base_url}/{path.lstrip('/')}"
        if query_params:
            upstream_url += f"?{query_params}"

        # 2. Prepare headers and timeouts.
        proxy_headers = self._prepare_proxy_headers(token, headers)
        timeout_config = self.config.timeouts
        timeout = httpx.Timeout(
            connect=timeout_config.connect,
            read=timeout_config.read,
            write=timeout_config.write,
            pool=timeout_config.pool
        )
        
        # 3. Build the request object.
        upstream_request = client.build_request(
            method=method,
            url=upstream_url,
            headers=proxy_headers,
            content=content,
            timeout=timeout,
        )
        
        # 4. Delegate to the centralized, reliable sender method.
        return await self._send_proxy_request(client, upstream_request)


