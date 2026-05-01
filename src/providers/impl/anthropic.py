# src/providers/impl/anthropic.py

import json
import logging
from collections.abc import AsyncGenerator, AsyncIterable
from typing import Any

import httpx

from src.core.constants import ErrorReason
from src.core.models import CheckResult, RequestDetails
from src.providers.base import AIBaseProvider

logger = logging.getLogger(__name__)


class AnthropicProvider(AIBaseProvider):
    """
    Provider for Anthropic API (Claude models).

    This class implements the IProvider interface for Anthropic's Messages API,
    supporting authentication via x-api-key header, streaming, and proper
    error mapping according to Anthropic's error response format.
    """

    # Anthropic API version header value
    ANTHROPIC_VERSION = "2023-06-01"

    def _get_headers(self, token: str) -> dict[str, str] | None:
        """
        Constructs the necessary authentication headers for Anthropic API requests.

        Args:
            token: The API token for Anthropic.

        Returns:
            A dictionary containing x-api-key, anthropic-version, and content-type headers,
            or None if the token is empty.
        """
        if not token:
            return None

        return {
            "x-api-key": token,
            "anthropic-version": self.ANTHROPIC_VERSION,
            "content-type": "application/json",
        }

    async def parse_request_details(self, path: str, content: bytes) -> RequestDetails:
        """
        Parses a JSON request body to extract the model name for Anthropic Messages API.

        Args:
            path: The URL path of the original request (ignored for model extraction).
            content: The raw byte content (body) of the original request.

        Returns:
            A RequestDetails object with the parsed model name.

        Raises:
            ValueError: If the request body is empty, not valid JSON, or is missing
                        the required 'model' field.
        """
        logger.debug(f"Parsing request details for Anthropic provider '{self.name}'.")
        try:
            if not content:
                raise ValueError("Request body is empty.")

            json_data: dict[str, Any] = json.loads(content)

            model_name = json_data.get("model")
            if not model_name or not isinstance(model_name, str):
                raise KeyError("Request body is missing a valid 'model' string field.")

            logger.debug(
                f"Successfully parsed model '{model_name}' from Anthropic request body."
            )
            return RequestDetails(model_name=model_name)

        except json.JSONDecodeError as e:
            error_msg = f"Failed to parse request body as JSON: {e}"
            logger.warning(error_msg)
            raise ValueError(error_msg) from e
        except (KeyError, TypeError) as e:
            error_msg = f"Invalid request body structure: {e}"
            logger.warning(error_msg)
            raise ValueError(error_msg) from e

    @staticmethod
    def _map_status_code_to_reason(status_code: int) -> ErrorReason:
        """
        Maps an HTTP status code from Anthropic API to a standardized ErrorReason enum.

        Args:
            status_code: The HTTP status code returned by Anthropic API.

        Returns:
            The corresponding ErrorReason enum value.
        """
        # Specific Anthropic error mappings
        if status_code == 400:
            return ErrorReason.BAD_REQUEST
        if status_code == 401:
            return ErrorReason.INVALID_KEY
        if status_code == 402:
            return ErrorReason.NO_QUOTA
        if status_code == 403:
            return ErrorReason.NO_ACCESS
        if status_code == 404:
            return ErrorReason.NO_MODEL
        if status_code == 413:
            return ErrorReason.BAD_REQUEST
        if status_code == 429:
            return ErrorReason.RATE_LIMITED
        if status_code == 500:
            return ErrorReason.SERVER_ERROR
        if status_code == 504:
            return ErrorReason.TIMEOUT
        if status_code == 529:
            return ErrorReason.OVERLOADED

        # Categorical Error Mapping: Any other 4xx error is BAD_REQUEST
        if 400 <= status_code < 500:
            return ErrorReason.BAD_REQUEST

        # Any other 5xx error is SERVER_ERROR
        if status_code >= 500:
            return ErrorReason.SERVER_ERROR

        return ErrorReason.UNKNOWN

    async def _parse_proxy_error(
        self, response: httpx.Response, content: bytes | None = None
    ) -> CheckResult:
        """
        Parses a failed Anthropic API response into a standardized CheckResult.

        This method implements the Zero-Overhead pattern:
        - If content is None, it relies solely on status code mapping
        - If content is provided, it refines the error reason using error parsing rules

        Args:
            response: The failed httpx.Response object from Anthropic API.
            content: Optional pre-read body bytes. If None, the body was NOT read
                     (optimization) and should NOT be read here.

        Returns:
            A CheckResult object detailing the failure.
        """
        status_code = response.status_code

        # Use pre-read content if available
        response_bytes = content
        response_text = ""

        if response_bytes:
            response_text = response_bytes.decode(errors="ignore")

        # Access .elapsed (safe after .read() or .close() in base provider)
        try:
            response_time = response.elapsed.total_seconds()
        except RuntimeError:
            response_time = 0.0

        # Get default reason based on status code
        default_reason = self._map_status_code_to_reason(status_code)

        # Refine reason using error parsing rules (if configured AND content is available)
        refined_reason = default_reason
        if response_bytes:
            refined_reason = await self._refine_error_reason(
                response=response,
                default_reason=default_reason,
                body_bytes=response_bytes,
            )

        return CheckResult.fail(
            refined_reason, response_text, response_time, status_code
        )

    async def check(
        self, client: httpx.AsyncClient, token: str, **kwargs: Any
    ) -> CheckResult:
        """
        Checks the validity of an Anthropic API token by making a lightweight test request.

        This method performs a GET request to /v1/models endpoint which is a cheap
        way to validate the token without consuming tokens or quota.

        Args:
            client: The httpx.AsyncClient to use for the request.
            token: The API token to validate.
            **kwargs: Additional keyword arguments. Expected to contain 'model' key.

        Returns:
            A CheckResult indicating the success or failure of the check.
        """
        model = kwargs.get("model")
        if not model:
            return CheckResult.fail(
                ErrorReason.BAD_REQUEST, "Missing 'model' parameter in check method."
            )

        logger.debug(
            f"Checking Anthropic key ending '...{token[-4:]}' for model '{model}'."
        )

        headers = self._get_headers(token)
        if not headers:
            return CheckResult.fail(
                ErrorReason.INVALID_KEY, "Token is empty or invalid."
            )

        # Validate model exists in configuration
        model_info = self.config.models.get(model)
        if not model_info:
            msg = f"Configuration for model '{model}' not found in provider '{self.name}'."
            logger.error(msg)
            return CheckResult.fail(ErrorReason.BAD_REQUEST, msg)

        # Build the models endpoint URL
        api_url = f"{self.config.api_base_url.rstrip('/')}/v1/models"

        timeout_config = self.config.timeouts
        timeout = httpx.Timeout(
            connect=timeout_config.connect,
            read=timeout_config.read,
            write=timeout_config.write,
            pool=timeout_config.pool,
        )

        try:
            response = await client.get(api_url, headers=headers, timeout=timeout)

            response.raise_for_status()

            return CheckResult.success(
                response_time=response.elapsed.total_seconds(),
                status_code=response.status_code,
            )

        except httpx.TimeoutException:
            response_time = timeout.read if timeout.read is not None else 0.0
            return CheckResult.fail(
                ErrorReason.TIMEOUT, "Request timed out", response_time, 408
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

            reason = self._map_status_code_to_reason(status_code)

            # Refine reason using error parsing rules from provider-level config
            text = response.text
            refined = await self._refine_error_reason(
                response, reason, body_bytes=text.encode()
            )

            return CheckResult.fail(
                reason=refined,
                message=text,
                response_time=response.elapsed.total_seconds(),
                status_code=status_code,
            )
        except httpx.RequestError as e:
            return CheckResult.fail(ErrorReason.NETWORK_ERROR, str(e), status_code=503)

    async def inspect(
        self, client: httpx.AsyncClient, token: str, **kwargs: Any
    ) -> list[str]:
        """
        Inspects and returns a list of available models from the configuration.

        Args:
            client: The httpx.AsyncClient (not used, models come from config).
            token: The API token (not used, models come from config).
            **kwargs: Additional keyword arguments (unused).

        Returns:
            A list of model names configured for this provider.
        """
        logger.debug(
            f"Inspecting models for Anthropic provider '{self.name}' from configuration."
        )
        return list(self.config.models.keys())

    async def proxy_request(
        self,
        client: httpx.AsyncClient,
        token: str,
        method: str,
        headers: dict[str, str],
        path: str,
        query_params: str,
        content: bytes | AsyncGenerator[bytes],
    ) -> tuple[httpx.Response, CheckResult, bytes | None]:
        """
        Proxies the incoming request to the Anthropic API.

        This method constructs the full upstream URL, prepares headers with
        Anthropic-specific authentication, and delegates the actual request
        sending to the robust _send_proxy_request method from AIBaseProvider.

        Args:
            client: The httpx.AsyncClient to use for the request.
            token: The API token for Anthropic authentication.
            method: The HTTP method (e.g., "POST").
            headers: The original client request headers.
            path: The URL path from the client request.
            query_params: Query parameters from the client request.
            content: The request body, either as bytes or an AsyncGenerator for streaming.

        Returns:
            A 3-tuple of ``(httpx.Response, CheckResult, body_bytes | None)``.
        """
        # 1. Construct the full upstream URL.
        base_url = self.config.api_base_url.rstrip("/")
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
            pool=timeout_config.pool,
        )

        # 3. Build the request object.
        if isinstance(content, AsyncIterable):
            upstream_request = client.build_request(
                method=method,
                url=upstream_url,
                headers=proxy_headers,
                content=content,
                timeout=timeout,
            )
        else:
            upstream_request = client.build_request(
                method=method,
                url=upstream_url,
                headers=proxy_headers,
                content=content,
                timeout=timeout,
            )

        # 4. Delegate to the centralized, reliable sender method.
        return await self._send_proxy_request(client, upstream_request)
