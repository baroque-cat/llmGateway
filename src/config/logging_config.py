# src/config/logging_config.py

import logging
import sys

# REFACTORED: Import ConfigAccessor instead of the raw Config schema.
# This makes the function dependent on the safe interface, not the data structure.
from src.core.accessor import ConfigAccessor


class MetricsEndpointFilter(logging.Filter):
    """
    A custom filter to suppress log entries for the /metrics endpoint.
    This prevents Prometheus scrapes from cluttering the main application logs.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        # Return False to drop the record if it contains "/metrics"
        return "/metrics" not in record.getMessage()


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

    # Define the format for log messages for consistency across the application.
    # The new format is cleaner and avoids redundant [INFO] tags.
    log_format = "%(name)s: %(message)s"

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

    # Reduce the log level for third-party libraries that can be very verbose.
    # This keeps the application's logs clean and focused.
    logging.getLogger("apscheduler.executors.default").setLevel(logging.WARNING)
    logging.getLogger("urllib3.connectionpool").setLevel(logging.INFO)
    # Silence httpx logs as we will provide our own unified transaction logs.
    logging.getLogger("httpx").setLevel(logging.WARNING)

    # A log message to confirm that logging has been successfully configured.
    logging.getLogger(__name__).info(
        f"Logging configured successfully. Level set to {logging.getLevelName(log_level)}."
    )
