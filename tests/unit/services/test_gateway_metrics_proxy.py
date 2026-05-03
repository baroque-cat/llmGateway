"""Unit tests for the rewritten metrics_endpoint() in gateway_service.py.

Tests cover:
  UT-MP01–05: Auth delegation (validate_metrics_access / validate_metrics_token,
              MetricsAuthError → HTTPException wrapping)
  UT-MP06–10: Proxy behaviour (httpx.AsyncClient → Keeper, TransportError)
  UT-MP11–14: Lifespan purity (no get_collector / reset_collector / atexit /
              PROMETHEUS_MULTIPROC_DIR in gateway_service.py)
"""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient

from src.config.schemas import MetricsConfig
from src.services.gateway.gateway_service import create_app

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SOURCE_PATH = (
    Path(__file__).resolve().parents[3]
    / "src"
    / "services"
    / "gateway"
    / "gateway_service.py"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_accessor(
    enabled: bool = True,
    access_token: str = "secret-token",
) -> MagicMock:
    """Create a mock ConfigAccessor with the given metrics config."""
    accessor = MagicMock()
    accessor.get_metrics_config.return_value = MetricsConfig(
        enabled=enabled,
        access_token=access_token,
    )
    accessor.get_enabled_providers.return_value = {}
    accessor.get_database_dsn.return_value = "postgresql://test:test@localhost/test"
    accessor.get_pool_config.return_value = MagicMock(min_size=2, max_size=5)
    return accessor


def _mock_keeper_response(
    content: bytes = b"# HELP test A test\n# TYPE test gauge\ntest 42.0",
    content_type: str = "text/plain; version=0.0.4; charset=utf-8",
    status_code: int = 200,
) -> MagicMock:
    """Create a mock httpx.Response representing Keeper's /metrics response."""
    resp = MagicMock()
    resp.content = content
    resp.headers = {"content-type": content_type}
    resp.status_code = status_code
    return resp


def _make_mock_httpx_client(
    get_return: MagicMock | None = None,
    get_side_effect: Exception | None = None,
) -> AsyncMock:
    """Create a mock httpx.AsyncClient that works as an async context manager.

    The default ``AsyncMock.__aenter__`` returns a *new* mock, not ``self``.
    We must explicitly wire ``__aenter__.return_value`` back to the same
    instance so that attributes set on the outer mock (e.g. ``.get``) are
    visible inside the ``async with`` block.
    """
    client = AsyncMock()
    # Ensure ``async with client as c:`` yields the same mock object
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)

    if get_side_effect is not None:
        client.get = AsyncMock(side_effect=get_side_effect)
    elif get_return is not None:
        client.get = AsyncMock(return_value=get_return)

    return client


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_accessor() -> MagicMock:
    """Default mock accessor: metrics enabled, token = 'secret-token'."""
    return _make_mock_accessor(enabled=True, access_token="secret-token")


@pytest.fixture
def gateway_app(mock_accessor: MagicMock):
    """Create a FastAPI app with all startup dependencies mocked."""
    with (
        patch(
            "src.services.gateway.gateway_service.database.init_db_pool",
            new=AsyncMock(),
        ),
        patch(
            "src.services.gateway.gateway_service.database.close_db_pool",
            new=AsyncMock(),
        ),
        patch(
            "src.services.gateway.gateway_service.DatabaseManager",
        ) as mock_dm_cls,
        patch(
            "src.services.gateway.gateway_service.HttpClientFactory",
        ) as mock_hcf_cls,
        patch(
            "src.services.gateway.gateway_service.GatewayCache",
        ) as mock_gc_cls,
        patch(
            "src.services.gateway.gateway_service._cache_refresh_loop",
            new=AsyncMock(),
        ),
    ):
        mock_dm_cls.return_value.wait_for_schema_ready = AsyncMock()
        mock_gc_cls.return_value.populate_caches = AsyncMock()
        mock_hcf_cls.return_value.close_all = AsyncMock()

        app = create_app(mock_accessor)
        # Ensure accessor is available even if lifespan is not triggered
        app.state.accessor = mock_accessor
        yield app


@pytest.fixture
def client(gateway_app):
    """TestClient wired to the mocked gateway app."""
    return TestClient(gateway_app)


# ---------------------------------------------------------------------------
# TestMetricsEndpointAuthDelegation  (UT-MP01 – UT-MP05)
# ---------------------------------------------------------------------------


class TestMetricsEndpointAuthDelegation:
    """Verify that metrics_endpoint delegates auth validation to
    src.metrics.auth and wraps MetricsAuthError in HTTPException."""

    def test_mp01_metrics_disabled_returns_404(self, mock_accessor, client):
        """UT-MP01: When metrics are disabled, endpoint returns 404."""
        mock_accessor.get_metrics_config.return_value = MetricsConfig(
            enabled=False,
            access_token="secret-token",
        )
        resp = client.get(
            "/metrics",
            headers={"Authorization": "Bearer secret-token"},
        )
        assert resp.status_code == 404
        assert resp.json()["detail"] == "Metrics endpoint is disabled"

    def test_mp02_empty_access_token_returns_404(self, mock_accessor, client):
        """UT-MP02: Empty access_token is treated as disabled → 404."""
        mock_accessor.get_metrics_config.return_value = MetricsConfig(
            enabled=True,
            access_token="",
        )
        resp = client.get("/metrics")
        assert resp.status_code == 404
        assert resp.json()["detail"] == "Metrics endpoint is disabled"

    def test_mp03_missing_authorization_returns_401(self, mock_accessor, client):
        """UT-MP03: No Authorization header → validate_metrics_token
        raises MetricsAuthError(401) → endpoint wraps as HTTPException(401)."""
        mock_accessor.get_metrics_config.return_value = MetricsConfig(
            enabled=True,
            access_token="secret-token",
        )
        resp = client.get("/metrics")
        assert resp.status_code == 401
        assert resp.json()["detail"] == "Missing or invalid Authorization header"

    def test_mp04_invalid_bearer_token_returns_403(self, mock_accessor, client):
        """UT-MP04: Wrong Bearer token → validate_metrics_token raises
        MetricsAuthError(403) → endpoint wraps as HTTPException(403)."""
        mock_accessor.get_metrics_config.return_value = MetricsConfig(
            enabled=True,
            access_token="correct-token",
        )
        resp = client.get(
            "/metrics",
            headers={"Authorization": "Bearer wrong-token"},
        )
        assert resp.status_code == 403
        assert resp.json()["detail"] == "Invalid metrics access token"

    def test_mp05_valid_token_returns_200_with_keeper_metrics(
        self,
        mock_accessor,
        client,
    ):
        """UT-MP05: Valid Bearer token → 200 with proxied Keeper metrics."""
        mock_accessor.get_metrics_config.return_value = MetricsConfig(
            enabled=True,
            access_token="secret-token",
        )
        keeper_resp = _mock_keeper_response(
            content=b"# HELP llm_requests_total Total\nllm_requests_total 5",
        )
        mock_client = _make_mock_httpx_client(get_return=keeper_resp)

        with patch(
            "src.services.gateway.gateway_service.httpx.AsyncClient",
            return_value=mock_client,
        ):
            resp = client.get(
                "/metrics",
                headers={"Authorization": "Bearer secret-token"},
            )

        assert resp.status_code == 200
        assert b"llm_requests_total" in resp.content


# ---------------------------------------------------------------------------
# TestMetricsEndpointProxy  (UT-MP06 – UT-MP10)
# ---------------------------------------------------------------------------


class TestMetricsEndpointProxy:
    """Verify that metrics_endpoint proxies to Keeper via httpx.AsyncClient
    and correctly handles TransportError."""

    def test_mp06_keeper_available_returns_prometheus_text(self, client):
        """UT-MP06: Keeper is reachable; gateway returns Keeper's content
        and preserves the content-type header."""
        keeper_resp = _mock_keeper_response(
            content=b"# HELP test_metric A test\n"
            b"# TYPE test_metric gauge\ntest_metric 42.0",
            content_type="text/plain; version=0.0.4; charset=utf-8",
        )
        mock_client = _make_mock_httpx_client(get_return=keeper_resp)

        with patch(
            "src.services.gateway.gateway_service.httpx.AsyncClient",
            return_value=mock_client,
        ):
            resp = client.get(
                "/metrics",
                headers={"Authorization": "Bearer secret-token"},
            )

        assert resp.status_code == 200
        assert resp.content == keeper_resp.content
        assert "text/plain" in resp.headers.get("content-type", "")

    def test_mp07_keeper_unavailable_returns_502(self, client):
        """UT-MP07: httpx.ConnectError (TransportError subclass) → 502."""
        mock_client = _make_mock_httpx_client(
            get_side_effect=httpx.ConnectError("Connection refused"),
        )

        with patch(
            "src.services.gateway.gateway_service.httpx.AsyncClient",
            return_value=mock_client,
        ):
            resp = client.get(
                "/metrics",
                headers={"Authorization": "Bearer secret-token"},
            )

        assert resp.status_code == 502
        assert resp.json()["detail"] == "Keeper metrics unavailable"

    def test_mp08_keeper_returns_500_proxy_content_as_is(self, client):
        """UT-MP08: Keeper responds with HTTP 500; gateway proxies the
        raw content (Response defaults to status 200)."""
        keeper_resp = _mock_keeper_response(
            content=b"Internal Server Error from Keeper",
            content_type="text/plain",
            status_code=500,
        )
        mock_client = _make_mock_httpx_client(get_return=keeper_resp)

        with patch(
            "src.services.gateway.gateway_service.httpx.AsyncClient",
            return_value=mock_client,
        ):
            resp = client.get(
                "/metrics",
                headers={"Authorization": "Bearer secret-token"},
            )

        # Gateway proxies raw content; Response() defaults to 200
        assert resp.status_code == 200
        assert resp.content == b"Internal Server Error from Keeper"

    def test_mp09_keeper_complex_content_type_preserved(self, client):
        """UT-MP09: Keeper returns 'text/plain; version=0.0.4; charset=utf-8';
        gateway preserves it verbatim in the response content-type header."""
        keeper_resp = _mock_keeper_response(
            content=b"test_metric 1.0",
            content_type="text/plain; version=0.0.4; charset=utf-8",
        )
        mock_client = _make_mock_httpx_client(get_return=keeper_resp)

        with patch(
            "src.services.gateway.gateway_service.httpx.AsyncClient",
            return_value=mock_client,
        ):
            resp = client.get(
                "/metrics",
                headers={"Authorization": "Bearer secret-token"},
            )

        assert resp.status_code == 200
        ct = resp.headers["content-type"]
        # Starlette may append charset for text/* types that lack one,
        # but our media_type already includes charset=utf-8, so it is
        # preserved verbatim.
        assert "text/plain" in ct
        assert "version=0.0.4" in ct

    def test_mp10_httpx_timeout_returns_502(self, client):
        """UT-MP10: httpx.TimeoutException (TransportError subclass) → 502."""
        mock_client = _make_mock_httpx_client(
            get_side_effect=httpx.TimeoutException("Read timeout"),
        )

        with patch(
            "src.services.gateway.gateway_service.httpx.AsyncClient",
            return_value=mock_client,
        ):
            resp = client.get(
                "/metrics",
                headers={"Authorization": "Bearer secret-token"},
            )

        assert resp.status_code == 502
        assert resp.json()["detail"] == "Keeper metrics unavailable"


# ---------------------------------------------------------------------------
# TestMetricsEndpointLifespanNoCollector  (UT-MP11 – UT-MP14)
# ---------------------------------------------------------------------------


class TestMetricsEndpointLifespanNoCollector:
    """Verify that gateway_service.py does not reference collector,
    atexit, or PROMETHEUS_MULTIPROC_DIR — ensuring the rewritten
    metrics_endpoint is a pure auth-proxy with no collector coupling."""

    @pytest.fixture(autouse=True)
    def _load_source(self):
        self.source = SOURCE_PATH.read_text()

    def test_mp11_lifespan_does_not_call_get_collector(self):
        """UT-MP11: gateway_service.py must not call get_collector()."""
        assert "get_collector" not in self.source, (
            "gateway_service.py references get_collector — "
            "lifespan should not depend on the metrics collector"
        )

    def test_mp12_lifespan_does_not_call_reset_collector(self):
        """UT-MP12: gateway_service.py must not call reset_collector()."""
        assert "reset_collector" not in self.source, (
            "gateway_service.py references reset_collector — "
            "lifespan should not depend on the metrics collector"
        )

    def test_mp13_lifespan_does_not_use_atexit(self):
        """UT-MP13: gateway_service.py must not import or use atexit."""
        assert "atexit" not in self.source, (
            "gateway_service.py references atexit — "
            "lifespan should not register atexit hooks"
        )

    def test_mp14_lifespan_does_not_set_prometheus_multiproc_dir(self):
        """UT-MP14: gateway_service.py must not reference
        PROMETHEUS_MULTIPROC_DIR."""
        assert "PROMETHEUS_MULTIPROC_DIR" not in self.source, (
            "gateway_service.py references PROMETHEUS_MULTIPROC_DIR — "
            "lifespan should not manage Prometheus multiprocess directory"
        )
