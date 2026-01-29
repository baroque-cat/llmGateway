# src/providers/impl/gemini_base.py

import re
import logging
from abc import abstractmethod
from typing import Dict, List, Optional, Tuple

import httpx

from src.core.enums import ErrorReason
from src.core.models import CheckResult, RequestDetails
from src.providers.base import AIBaseProvider

logger = logging.getLogger(__name__)

# Regex to extract model name from a typical Gemini API path.
# Assumes paths like /v1beta/models/gemini-2.5-pro:generateContent
MODEL_FROM_PATH_REGEX = re.compile(r"/models/([^:]+)")


class GeminiBaseProvider(AIBaseProvider):
    """
    Abstract Base Class for providers that use Google's Generative AI APIs.

    This class centralizes common logic such as authentication headers,
    error mapping, and the core structure of health checks (Template Method pattern).
    Concrete implementations must provide specifics like how to build request URLs.
    """

    # --- Methods with Concrete Implementations (Shared Logic) ---

    def _get_headers(self, token: str) -> Optional[Dict[str, str]]:
        """
        Constructs headers for Gemini API, which uses the 'x-goog-api-key' header.
        This is common across all Google GenAI services.
        """
        if not token or not isinstance(token, str):
            return None
        return {
            "x-goog-api-key": token,
            "Content-Type": "application/json",
        }

    # --- Implementation of the error parsing contract from AIBaseProvider ---
    async def _parse_proxy_error(self, response: httpx.Response) -> CheckResult:
        """
        Parses a failed Gemini API response into a standardized CheckResult.

        This method implements the safe-access pattern required by httpx:
        1. Read the response body first.
        2. THEN, access properties like .elapsed.
        This definitively fixes the RuntimeError.
        
        Now enhanced with error parsing rules from configuration.
        """
        status_code = response.status_code

        # 1. Read the response body first. This makes other properties available.
        response_bytes = await response.aread()
        response_text = response_bytes.decode(errors="ignore")

        # 2. Now it is safe to access .elapsed.
        response_time = response.elapsed.total_seconds()

        # 3. Get default reason using the centralized mapping logic.
        default_reason = self._map_error_to_reason(status_code, response_text)
        
        # 4. Refine reason using error parsing rules (if configured)
        # Pass the already-read body to avoid re-reading
        refined_reason = await self._refine_error_reason(
            response=response,
            default_reason=default_reason,
            body_bytes=response_bytes
        )

        return CheckResult.fail(refined_reason, response_text, response_time, status_code)

    async def inspect(
        self, client: httpx.AsyncClient, token: str, **kwargs
    ) -> List[str]:
        """
        Inspects and returns a list of available models from the configuration.
        This logic is generic and reads keys from the multimodal 'models' dictionary.
        """
        logger.debug(
            f"Inspecting models for provider '{self.name}' by reading from config."
        )
        return list(self.config.models.keys())

    async def parse_request_details(self, path: str, content: bytes) -> RequestDetails:
        """
        Parses the URL path to extract the model name for Gemini APIs.
        This implementation ignores the request body content.

        Args:
            path: The URL path of the original request.
            content: The raw byte content (body) of the request (ignored).

        Returns:
            A RequestDetails object with the parsed model name.

        Raises:
            ValueError: If the model name cannot be extracted from the path.
        """
        # The content argument is ignored for this provider type, as per the design.
        _ = content

        match = MODEL_FROM_PATH_REGEX.search(path)
        if not match:
            raise ValueError(f"Could not extract model name from path: {path}")

        model_name = match.group(1)
        logger.debug(f"Successfully parsed model '{model_name}' from request path.")
        return RequestDetails(model_name=model_name)

    def _map_error_to_reason(self, status_code: int, response_text: str) -> ErrorReason:
        """
        Maps a Google API error response to a standardized ErrorReason.
        This is the central point for interpreting Google's error codes.
        """
        # The most reliable signal for a dead key is the specific error message.
        # This check should always have the highest priority.
        if "API_KEY_INVALID" in response_text:
            return ErrorReason.INVALID_KEY

        # Map status codes according to the specified logic.
        # These errors do not definitively mean the key is dead, just that the
        # request failed for a specific reason.
        if status_code == 400:
            return ErrorReason.BAD_REQUEST
        if status_code == 403:
            return ErrorReason.NO_ACCESS
        if status_code == 404:
            return ErrorReason.NO_MODEL
        if status_code == 429:
            return ErrorReason.NO_QUOTA
        if status_code == 500:
            return ErrorReason.SERVER_ERROR
        if status_code == 503:
            return ErrorReason.OVERLOADED
        if status_code == 504:
            return ErrorReason.TIMEOUT

        # Fallback for any other unhandled error.
        return ErrorReason.UNKNOWN

    async def check(
        self, client: httpx.AsyncClient, token: str, **kwargs
    ) -> CheckResult:
        """
        Template Method for checking the validity of a Gemini API token.

        This method contains the shared logic for making requests and handling
        errors, while delegating the creation of the specific URL and payload
        to the concrete subclass via `_build_check_request_args`.
        
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
        logger.debug(
            f"Checking Gemini key ending '...{token[-4:]}' for model '{model}'."
        )

        headers = self._get_headers(token)
        if not headers:
            return CheckResult.fail(
                ErrorReason.INVALID_KEY, "Token is empty or invalid."
            )

        try:
            # Delegate creation of request specifics to the subclass.
            request_args = self._build_check_request_args(model)
            api_url = request_args["api_url"]
            payload = request_args["payload"]

        except (KeyError, ValueError) as e:
            # This handles cases where the model is not found in the config.
            logger.error(f"Configuration error for provider '{self.name}': {e}")
            return CheckResult.fail(ErrorReason.BAD_REQUEST, str(e))

        timeout_config = self.config.timeouts
        timeout = httpx.Timeout(
            connect=timeout_config.connect,
            read=timeout_config.read,
            write=timeout_config.write,
            pool=timeout_config.pool,
        )

        try:
            response = await client.post(
                api_url, headers=headers, json=payload, timeout=timeout
            )
            response.raise_for_status()
            return CheckResult.success(
                response_time=response.elapsed.total_seconds(),
                status_code=response.status_code,
            )

        except httpx.TimeoutException:
            return CheckResult.fail(
                ErrorReason.TIMEOUT, "Request timed out", timeout.read, 504
            )
        except httpx.ProxyError as e:
            return CheckResult.fail(
                ErrorReason.NETWORK_ERROR, f"Proxy error: {e}", status_code=503
            )
        except httpx.ConnectError as e:
            return CheckResult.fail(
                ErrorReason.NETWORK_ERROR, f"Connection error: {e}", status_code=503
            )
        except httpx.HTTPStatusError as e:
            response = e.response
            status_code = response.status_code
            
            # Special handling for worker: 400 errors in check() likely indicate invalid key
            # since the request format is predetermined and correct
            if status_code == 400:
                reason = ErrorReason.INVALID_KEY
                logger.debug(f"Worker check received 400 error, treating as {reason.value} for key validation")
            else:
                # Use the centralized error mapping method.
                reason = self._map_error_to_reason(status_code, response.text)
            
            return CheckResult.fail(
                reason=reason,
                message=response.text,
                response_time=response.elapsed.total_seconds(),
                status_code=status_code,
            )
        except httpx.RequestError as e:
            return CheckResult.fail(ErrorReason.NETWORK_ERROR, str(e), status_code=503)

    # --- Abstract Methods (Contracts for Subclasses) ---

    @abstractmethod
    def _build_check_request_args(self, model: str) -> Dict:
        """
        (Abstract) Constructs the API URL and payload for a health check.
        Must be implemented by concrete subclasses.

        Returns:
            A dictionary containing 'api_url' (str) and 'payload' (dict).
        """
        raise NotImplementedError

    @abstractmethod
    async def proxy_request(
        self,
        client: httpx.AsyncClient,
        token: str,
        method: str,
        headers: Dict,
        path: str,
        query_params: str,
        content: bytes,
    ) -> Tuple[httpx.Response, CheckResult]:
        """
        (Abstract) Proxies an incoming client request to the target API provider.
        Must be implemented by concrete subclasses.
        """
        raise NotImplementedError
