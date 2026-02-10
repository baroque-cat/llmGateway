# src/providers/base.py

import json
import logging
import re
from abc import abstractmethod
from collections.abc import AsyncGenerator
from typing import Any

import httpx

from src.config.schemas import ErrorParsingRule, ProviderConfig
from src.core.constants import ErrorReason
from src.core.interfaces import IProvider

# --- Import the required data models ---
from src.core.models import CheckResult, RequestDetails

# --- Get a logger for this module ---
logger = logging.getLogger(__name__)


class AIBaseProvider(IProvider):
    """
    Abstract Base Class for AI providers (Async, Framework-Agnostic, DI-ready).

    It enforces the IProvider contract and provides a common structure
    and helper methods for all concrete provider implementations.
    """

    def __init__(self, provider_name: str, config: ProviderConfig):
        """
        Initializes the base provider.

        Args:
            provider_name: The unique name of the provider instance.
            config: The configuration object specific to this provider.
        """
        if not provider_name:
            raise ValueError("Provider name cannot be empty.")

        self.name = provider_name
        self.config = config

    def _prepare_proxy_headers(
        self, token: str, incoming_headers: dict[str, str]
    ) -> dict[str, str]:
        """
        Prepares headers for the outbound proxy request from a dictionary.

        This method cleans the incoming headers and merges them with the
        provider-specific headers required for upstream authentication.
        It operates on a simple dictionary, making it framework-agnostic.

        Args:
            token: The API token for the upstream service.
            incoming_headers: A dictionary of headers from the client's request.

        Returns:
            A dictionary of cleaned and prepared headers for the outbound request.
        """
        cleaned_headers = {k.lower(): v for k, v in incoming_headers.items()}

        headers_to_remove = [
            "host",
            "authorization",
            "x-goog-api-key",
            "content-length",
            "content-type",
        ]
        for h in headers_to_remove:
            cleaned_headers.pop(h, None)

        provider_headers = self._get_headers(token) or {}
        cleaned_headers.update({k.lower(): v for k, v in provider_headers.items()})

        return cleaned_headers

    # --- NEW: Error parsing helper methods ---

    async def _refine_error_reason(
        self,
        response: httpx.Response,
        default_reason: ErrorReason,
        body_bytes: bytes | None = None,
        response_data: dict[str, Any] | None = None,
    ) -> ErrorReason:
        """
        Refines the error reason based on error parsing rules from configuration.

        This method analyzes the response body using configured error parsing rules
        to provide more accurate error classification. For example, it can distinguish
        between different types of 400 errors (e.g., "Arrearage" vs format errors).

        Args:
            response: The HTTP response from the upstream API
            default_reason: The default error reason based on HTTP status code
            body_bytes: Optional pre-read response body bytes (to avoid re-reading)
            response_data: Optional pre-parsed JSON response data

        Returns:
            Refined error reason if a rule matches, otherwise the default reason
        """
        # Check if error parsing is enabled and has rules
        error_config = self.config.gateway_policy.error_parsing
        if not error_config.enabled or not error_config.rules:
            return default_reason

        # Get rules for this status code
        rules: list[ErrorParsingRule] = [
            r for r in error_config.rules if r.status_code == response.status_code
        ]
        if not rules:
            return default_reason

        # Parse response body if not already provided
        parsed_data = response_data
        if parsed_data is None:
            try:
                if body_bytes is None:
                    body_bytes = await response.aread()
                if body_bytes:
                    parsed_data = json.loads(
                        body_bytes.decode("utf-8", errors="ignore")
                    )
                else:
                    # Empty body, can't parse
                    return default_reason
            except (json.JSONDecodeError, UnicodeDecodeError, AttributeError):
                # If we can't parse the body, return the default reason
                return default_reason

        # Apply rules in priority order (higher priority first)
        matched_rules: list[ErrorParsingRule] = []
        for rule in sorted(rules, key=lambda x: x.priority, reverse=True):
            try:
                value = self._extract_json_value(parsed_data, rule.error_path)
                if value and re.search(rule.match_pattern, str(value), re.IGNORECASE):
                    matched_rules.append(rule)
            except (KeyError, TypeError, re.error):
                # Skip rules that can't be evaluated
                continue

        # Select the highest priority matched rule
        if matched_rules:
            best_rule = max(matched_rules, key=lambda x: x.priority)
            try:
                return ErrorReason(best_rule.map_to)
            except ValueError:
                logger.warning(
                    f"Invalid map_to value '{best_rule.map_to}' in error parsing rule "
                    f"for provider '{self.name}'. Using default reason."
                )

        return default_reason

    def _extract_json_value(self, data: dict[str, Any], path: str) -> Any | None:
        """
        Extracts a value from a nested dictionary using a dot-separated path.

        Args:
            data: The JSON data as a dictionary
            path: Dot-separated path to the field (e.g., "error.type")

        Returns:
            The extracted value or None if the path doesn't exist
        """
        parts = path.split(".")
        current = data
        for part in parts:
            if isinstance(current, dict) and part in current:
                current = current[part]
            else:
                return None
        return current

    async def _check_fast_fail(self, response: httpx.Response) -> CheckResult | None:
        """
        Checks if the response status code matches any entry in the worker's fast_status_mapping.
        If a match is found, returns a CheckResult with the mapped ErrorReason immediately.
        This enables "fast fail" behavior for worker health checks without reading the response body.

        Args:
            response: The HTTP response from the upstream API

        Returns:
            CheckResult if a fast fail condition is met, None otherwise
        """
        status_code = response.status_code
        health_policy = self.config.worker_health_policy

        if status_code in health_policy.fast_status_mapping:
            reason_str = health_policy.fast_status_mapping[status_code]
            try:
                reason = ErrorReason(reason_str)
            except ValueError:
                logger.warning(
                    f"Invalid ErrorReason '{reason_str}' in worker_health_policy.fast_status_mapping "
                    f"for provider '{self.name}'. Fallback to UNKNOWN."
                )
                reason = ErrorReason.UNKNOWN

            # Log the fast fail event
            logger.debug(
                f"Worker fast fail for provider '{self.name}': Status {status_code} mapped to {reason.value}"
            )

            return CheckResult.fail(
                reason=reason,
                message=f"Worker fast fail: {reason.value} (Status {status_code})",
                status_code=status_code,
            )

        return None

    # --- REFACTORED: Protected helper method for sending requests (Template Method pattern) ---
    async def _send_proxy_request(
        self, client: httpx.AsyncClient, request: httpx.Request
    ) -> tuple[httpx.Response, CheckResult]:
        """
        Sends a pre-built proxy request and parses the result.

        This method encapsulates the common logic for sending a request,
        handling network errors, and processing successful/failed responses.
        It delegates the parsing of provider-specific errors to the
        `_parse_proxy_error` method.

        Args:
            client: The httpx.AsyncClient to use for the request.
            request: The pre-built httpx.Request object.

        Returns:
            A tuple containing the raw httpx.Response and a parsed CheckResult.
        """
        try:
            upstream_response = await client.send(request, stream=True)

            if upstream_response.is_success:
                # --- FIXED: Do NOT access .elapsed on a successful streaming response ---
                # The response body has not been read yet, so accessing .elapsed
                # would raise a RuntimeError. For a successful proxy, we only
                # need to confirm it's okay and pass the status code.
                check_result = CheckResult.success(
                    status_code=upstream_response.status_code
                )
            else:
                # --- NEW: Zero-Overhead Error Handling Pipeline ---
                status_code = upstream_response.status_code
                gateway_policy = self.config.gateway_policy

                # 1. Fast Status Mapping (Highest Priority - Fast Fail)
                if status_code in gateway_policy.fast_status_mapping:
                    reason_str = gateway_policy.fast_status_mapping[status_code]
                    try:
                        reason = ErrorReason(reason_str)
                    except ValueError:
                        logger.warning(
                            f"Invalid ErrorReason '{reason_str}' in unsafe_status_mapping for '{self.name}'. "
                            f"Fallback to UNKNOWN."
                        )
                        reason = ErrorReason.UNKNOWN

                    # STOP: Close stream without reading body
                    await upstream_response.aclose()

                    check_result = CheckResult.fail(
                        reason=reason,
                        message=f"Fast fail: {reason.value} (Status {status_code})",
                        status_code=status_code,
                    )

                # 2. Debug Mode or Error Parsing (Read Body)
                else:
                    should_read_body = False

                    # Check Debug Mode
                    if gateway_policy.debug_mode == "full_body":
                        should_read_body = True

                    # Check Error Parsing Rules
                    elif gateway_policy.error_parsing.enabled:
                        # Only read if there is a rule for this specific status code
                        for rule in gateway_policy.error_parsing.rules:
                            if rule.status_code == status_code:
                                should_read_body = True
                                break

                    if should_read_body:
                        # READ: Read body into memory
                        try:
                            content_bytes = await upstream_response.aread()
                        except Exception as e:
                            logger.error(f"Failed to read error response body: {e}")
                            content_bytes = None

                        # Delegate parsing with content
                        check_result = await self._parse_proxy_error(
                            upstream_response, content_bytes
                        )
                    else:
                        # STOP: Fast Fallback (Default Behavior)
                        # Do NOT read body. Close stream.
                        await upstream_response.aclose()

                        # Delegate parsing WITHOUT content (will use status code mapping)
                        check_result = await self._parse_proxy_error(
                            upstream_response, None
                        )

        except httpx.RequestError as e:
            error_message = f"Upstream request failed with a network-level error: {e}"
            logger.error(error_message)
            check_result = CheckResult.fail(
                ErrorReason.NETWORK_ERROR, error_message, status_code=503
            )
            # Create a synthetic response for the gateway to handle gracefully.
            upstream_response = httpx.Response(503, content=error_message.encode())

        return upstream_response, check_result

    # --- Abstract method for provider-specific error parsing ---
    @abstractmethod
    async def _parse_proxy_error(
        self, response: httpx.Response, content: bytes | None = None
    ) -> CheckResult:
        """
        (Abstract) Parses a failed httpx.Response to generate a CheckResult.

        This method MUST be implemented by subclasses. It is responsible for
        mapping the provider-specific error to a standardized ErrorReason.

        Args:
            response: The failed httpx.Response object.
            content: Optional pre-read body bytes. If None, the body was NOT read
                     (optimization) and should NOT be read here.

        Returns:
            A CheckResult object detailing the failure.
        """
        raise NotImplementedError

    @abstractmethod
    async def parse_request_details(self, path: str, content: bytes) -> RequestDetails:
        """
        (Abstract) Parses the raw incoming request to extract provider-specific details.
        Must be implemented by subclasses.
        """
        raise NotImplementedError

    @abstractmethod
    def _get_headers(self, token: str) -> dict[str, str] | None:
        """
        (Abstract) Constructs the necessary authentication headers for API requests.
        Must be implemented by subclasses.
        """
        raise NotImplementedError

    @abstractmethod
    async def check(
        self, client: httpx.AsyncClient, token: str, **kwargs: Any
    ) -> CheckResult:
        """
        (Abstract) Checks if an API token is valid for this provider. (Async)
        """
        raise NotImplementedError

    @abstractmethod
    async def inspect(
        self, client: httpx.AsyncClient, token: str, **kwargs: Any
    ) -> list[str]:
        """
        (Abstract) Inspects the capabilities associated with a token. (Async)
        """
        raise NotImplementedError

    @abstractmethod
    async def proxy_request(
        self,
        client: httpx.AsyncClient,
        token: str,
        method: str,
        headers: dict[str, str],
        path: str,
        query_params: str,
        content: bytes | AsyncGenerator[bytes],
    ) -> tuple[httpx.Response, CheckResult]:
        """
        (Abstract) Proxies an incoming client request to the target API provider. (Async)
        """
        raise NotImplementedError
