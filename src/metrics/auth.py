"""Metrics authentication module — pure domain functions.

Provides domain exception ``MetricsAuthError`` and validation
functions ``validate_metrics_access`` and ``validate_metrics_token``
with no dependencies on FastAPI, HTTPException, or any web framework.
"""

from __future__ import annotations

from src.core.accessor import ConfigAccessor


class MetricsAuthError(Exception):
    """Domain exception for metrics authentication failures.

    Attributes:
        status_code: HTTP status code to return (404, 401, or 403).
        detail: Human-readable error message.
    """

    def __init__(self, status_code: int, detail: str) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(detail)


def validate_metrics_access(accessor: ConfigAccessor) -> str:
    """Check that the metrics endpoint is enabled and has a token configured.

    Args:
        accessor: Configuration accessor providing ``get_metrics_config()``.

    Returns:
        The expected access token string.

    Raises:
        MetricsAuthError(404): If metrics are disabled or no access token is configured.
    """
    metrics_config = accessor.get_metrics_config()
    if not metrics_config.enabled:
        raise MetricsAuthError(404, "Metrics endpoint is disabled")

    token = metrics_config.access_token
    if not token or not token.strip():
        raise MetricsAuthError(404, "Metrics endpoint is disabled")

    return token


def validate_metrics_token(raw_token: str | None, expected: str) -> None:
    """Compare a pre-extracted token against the expected value.

    Args:
        raw_token: The token extracted from the request (without ``Bearer`` prefix).
        expected: The configured expected token.

    Raises:
        MetricsAuthError(401): If ``raw_token`` is ``None`` or empty.
        MetricsAuthError(403): If ``raw_token`` does not match ``expected``.
    """
    if not raw_token:
        raise MetricsAuthError(401, "Missing or invalid Authorization header")

    if raw_token != expected:
        raise MetricsAuthError(403, "Invalid metrics access token")
