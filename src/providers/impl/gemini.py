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

    # --- REFACTORED: Now uses the centralized helper method from AIBaseProvider ---
    async def proxy_request(
        self, client: httpx.AsyncClient, token: str, method: str, headers: Dict, path: str, query_params: str, content: bytes
    ) -> Tuple[httpx.Response, CheckResult]:
        """
        Proxies the incoming request to the Gemini API.
        
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
            connect=timeout_config.connect, read=timeout_config.read,
            write=timeout_config.write, pool=timeout_config.pool
        )
        
        # 3. Build the request object.
        upstream_request = client.build_request(
            method=method, url=upstream_url, headers=proxy_headers,
            content=content, timeout=timeout,
        )
        
        # 4. Delegate to the centralized, reliable sender method.
        return await self._send_proxy_request(client, upstream_request)
