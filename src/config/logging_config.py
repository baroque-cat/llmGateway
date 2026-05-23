# src/config/logging_config.py

import logging
import sys
from collections.abc import Callable
from typing import Any

# REFACTORED: Import ConfigAccessor instead of the raw Config schema.
# This makes the function dependent on the safe interface, not the data structure.
from src.config.schemas import HttpClientLoggingConfig
from src.core.accessor import ConfigAccessor

# Module-level trace handler callable, set by _setup_http_client_logging()
# when trace_enabled=True. Used by HttpClientFactory to attach to
# httpx request extensions={"trace": handler}.
_trace_handler: Callable[[dict[str, Any]], None] | None = None


def get_trace_handler() -> Callable[[dict[str, Any]], None] | None:
    """Returns the trace handler if trace_enabled, or None."""
    return _trace_handler


class MetricsEndpointFilter(logging.Filter):
    """
    A custom filter to suppress log entries for the /metrics endpoint.
    This prevents Prometheus scrapes from cluttering the main application logs.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        # Return False to drop the record if it contains "/metrics"
        return "/metrics" not in record.getMessage()


class ComponentNameFilter(logging.Filter):
    """
    A transparent filter that replaces full module paths with semantic component names.

    Applied once to the root logger, it sets the ``component`` attribute on every
    ``LogRecord`` without requiring changes to any ``logging.getLogger(__name__)``
    calls in the application.
    """

    _MAP: tuple[tuple[str, str], ...] = (
        ("__main__", "main"),
        ("src.config", "config"),
        ("src.services.gateway", "gateway"),
        ("src.services.keeper", "keeper"),
        ("src.services.key_probe", "probe"),
        ("src.core.probes", "batch"),
        ("src.services.key_purger", "purger"),
        ("src.services.db_maintainer", "vacuum"),
        ("src.services.inventory_exporter", "export"),
        ("src.metrics", "metrics"),
        ("src.services.synchronizers", "sync"),
        ("src.db.database", "database"),
        ("src.providers", "provider"),
        ("src.core.http_client_factory", "http"),
        ("src.core.retry", "retry"),
        ("src.core.atomic_io", "storage"),
    )

    def filter(self, record: logging.LogRecord) -> bool:
        module = record.name
        for prefix, name in self._MAP:
            if module.startswith(prefix):
                record.component = name
                break
        else:
            record.component = module.rsplit(".", 1)[-1]
        return True


def _setup_http_client_logging(cfg: HttpClientLoggingConfig) -> None:
    """
    Sets log levels for httpx and httpcore libraries independently from the
    application log level.

    If ``trace_enabled`` is True, also creates a trace handler callable that
    ``HttpClientFactory`` attaches to each request via
    ``extensions={"trace": handler}``.

    Args:
        cfg: The ``HttpClientLoggingConfig`` from the ``logging.http_client``
            config section.
    """
    global _trace_handler

    try:
        logging.getLogger("httpx").setLevel(getattr(logging, cfg.httpx_level))
    except (TypeError, AttributeError):
        logging.getLogger("httpx").setLevel(logging.WARNING)

    try:
        logging.getLogger("httpcore").setLevel(getattr(logging, cfg.httpcore_level))
    except (TypeError, AttributeError):
        logging.getLogger("httpcore").setLevel(logging.WARNING)

    if cfg.trace_enabled:
        trace_logger = logging.getLogger("httpcore.trace")

        def _trace_handler_impl(event: dict[str, Any]) -> None:
            event_type = event.get("event", "unknown")
            info = event.get("info", {})
            msg_parts: list[str] = [event_type]
            for key, val in sorted(info.items()):
                msg_parts.append(f"{key}={val}")
            trace_logger.debug(" | ".join(msg_parts))

        _trace_handler = _trace_handler_impl
    else:
        _trace_handler = None


def setup_logging(accessor: ConfigAccessor) -> None:
    """
    Configures the root logger for the entire application based on the global config.

    This function should be called once at the application's entry point.
    It sets the logging level based on the debug flag and directs all logs to stdout.

    Args:
        accessor: The ConfigAccessor instance providing access to configuration.
    """
    # Use the configured log level from the config, defaulting to INFO.
    config_log_level = accessor.get_logging_config().level
    log_level = getattr(logging, config_log_level.upper(), logging.INFO)

    # Define the format for log messages.
    # Format: LEVEL | COMPONENT | MESSAGE
    # No asctime — timestamps are provided by the container runtime (docker/podman -t).
    # No ANSI colors — plain text for container log collectors.
    log_format = "%(levelname)-8s | %(component)-10s | %(message)s"

    # Get the root logger. All other loggers created with logging.getLogger(__name__)
    # will inherit this configuration.
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)

    # Remove any existing handlers to avoid duplicate logs if this function is called more than once.
    if root_logger.hasHandlers():
        root_logger.handlers.clear()

    # Create a handler to stream logs to standard output (the console).
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(log_level)

    # Attach the ComponentNameFilter at handler level so that all propagated
    # records (from child loggers) are processed before hitting the formatter.
    handler.addFilter(ComponentNameFilter())

    # Create a formatter and attach it to the handler.
    formatter = logging.Formatter(log_format)
    handler.setFormatter(formatter)

    # Add the configured handler to the root logger.
    root_logger.addHandler(handler)

    # Apply the custom filter to the uvicorn access logger to hide /metrics calls.
    uvicorn_access_logger = logging.getLogger("uvicorn.access")
    uvicorn_access_logger.addFilter(MetricsEndpointFilter())
    # Silence standard uvicorn access logs for non-metrics requests to prevent duplication
    # with our own GATEWAY_ACCESS logs.
    uvicorn_access_logger.setLevel(logging.WARNING)

    # Suppress uvicorn.error WARNING messages (e.g. "Invalid HTTP request received"
    # caused by scanners, health probes, or malformed client requests).
    # True errors (CRITICAL/ERROR) remain visible.
    logging.getLogger("uvicorn.error").setLevel(logging.ERROR)

    # Reduce the log level for third-party libraries that can be very verbose.
    # This keeps the application's logs clean and focused.
    logging.getLogger("apscheduler.scheduler").setLevel(logging.WARNING)
    logging.getLogger("apscheduler.executors.default").setLevel(logging.WARNING)
    logging.getLogger("urllib3.connectionpool").setLevel(logging.INFO)
    # Configure httpx and httpcore logger levels from config.
    _setup_http_client_logging(accessor.get_logging_config().http_client)

    # A log message to confirm that logging has been successfully configured.
    logging.getLogger(__name__).info(
        f"Logging configured successfully. Level set to {logging.getLevelName(log_level)}."
    )
