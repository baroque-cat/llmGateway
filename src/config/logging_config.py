# src/config/logging_config.py

import logging
import sys

# REFACTORED: Import ConfigAccessor instead of the raw Config schema.
# This makes the function dependent on the safe interface, not the data structure.
from src.core.accessor import ConfigAccessor

def setup_logging(accessor: ConfigAccessor):
    """
    Configures the root logger for the entire application based on the global config.

    This function should be called once at the application's entry point.
    It sets the logging level based on the debug flag and directs all logs to stdout.

    Args:
        accessor: The ConfigAccessor instance providing access to configuration.
    """
    # Use INFO as the default log level for the application.
    log_level = logging.INFO

    # Define the format for log messages for consistency across the application.
    # Format includes timestamp, logger name, log level, and the message itself.
    log_format = '%(name)s - [%(levelname)s] - %(message)s'

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

    # Reduce the log level for third-party libraries that can be very verbose.
    # This keeps the application's logs clean and focused.
    logging.getLogger('apscheduler.executors.default').setLevel(logging.WARNING)
    logging.getLogger('urllib3.connectionpool').setLevel(logging.INFO)

    # A log message to confirm that logging has been successfully configured.
    logging.getLogger(__name__).info(f"Logging configured successfully. Level set to {logging.getLevelName(log_level)}.")
