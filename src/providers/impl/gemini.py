# src/providers/impl/gemini.py

import logging
from typing import Dict, Tuple

import httpx

from src.core.enums import ErrorReason
from src.core.models import CheckResult
from src.providers.impl.gemini_base import GeminiBaseProvider

logger = logging.getLogger(__name__)

class GeminiProvider(GeminiBaseProvider):
    """
    Concrete provider for Google Gemini Text and Image models.

    This class inherits all common logic from GeminiBaseProvider and only
    implements the specific methods required to build URLs and proxy requests
    for text/image generation, driven by the new multimodal configuration.
    """

    def _build_check_request_args(self, model: str) -> Dict:
        """
        Constructs the API URL and payload for a health check using config values.
        This implementation is specific to text and image models.
        """
        model_info = self.config.models.get(model)
        if not model_info:
            raise ValueError(f"Configuration for model '{model}' not found.")

        base_url = self.config.api_base_url.rstrip('/')
        
        # Build URL dynamically using the model name and the configured suffix.
        # e.g., .../models/gemini-2.5-pro:generateContent
        api_url = f"{base_url}/v1beta/models/{model}{model_info.endpoint_suffix}"
        
        # Use the payload directly from the configuration.
        payload = model_info.test_payload

        return {"api_url": api_url, "payload": payload}

    async def proxy_request(
        self, client: httpx.AsyncClient, token: str, method: str, headers: Dict, path: str, content: bytes
    ) -> Tuple[httpx.Response, CheckResult]:
        """
        Proxies the incoming request to the Gemini API with streaming support.
        This implementation is generic enough for standard text/image proxying.
        """
        base_url = self.config.api_base_url.rstrip('/')
        upstream_url = f"{base_url}/{path.lstrip('/')}"
        
        proxy_headers = self._prepare_proxy_headers(token, headers)
        
        timeout_config = self.config.timeouts
        timeout = httpx.Timeout(
            connect=timeout_config.connect, read=timeout_config.read,
            write=timeout_config.write, pool=timeout_config.pool
        )
        
        try:
            upstream_request = client.build_request(
                method=method, url=upstream_url, headers=proxy_headers,
                content=content, timeout=timeout,
            )
            upstream_response = await client.send(upstream_request, stream=True)
            
            status_code = upstream_response.status_code
            response_time = upstream_response.elapsed.total_seconds()
            
            if upstream_response.is_success:
                check_result = CheckResult.success(response_time=response_time, status_code=status_code)
            else:
                response_text = await upstream_response.aread()
                # Use the centralized error mapping method from the base class.
                reason = self._map_error_to_reason(status_code, response_text.decode())
                check_result = CheckResult.fail(reason, response_text.decode(), response_time, status_code)
            
        except httpx.RequestError as e:
            error_message = f"Upstream request failed: {e}"
            logger.error(error_message)
            check_result = CheckResult.fail(ErrorReason.NETWORK_ERROR, error_message, status_code=503)
            upstream_response = httpx.Response(503, content=error_message.encode())

        return upstream_response, check_result
