# src/services/statistics_logger.py

import json
import logging
import logging.handlers
import os
from collections import defaultdict
from datetime import UTC, datetime

# REFACTORED: Import ConfigAccessor to replace the direct dependency on Config.
from src.core.accessor import ConfigAccessor
from src.db.database import DatabaseManager

# Get a logger for this module. The main application entry point will configure its output.
module_logger = logging.getLogger(__name__)


class StatisticsLogger:
    """
    A service dedicated to periodically collecting and logging summary statistics (Async Version).

    This service queries the database for an aggregated view of resource statuses,
    formats this data into JSON Lines (.jsonl), and writes it to provider-specific
    log files with built-in rotation.
    """

    # REFACTORED: The constructor now accepts ConfigAccessor for proper dependency injection.
    def __init__(self, accessor: ConfigAccessor, db_manager: DatabaseManager):
        """
        Initializes the StatisticsLogger.

        Args:
            accessor: An instance of ConfigAccessor for safe config access.
            db_manager: An instance of the DatabaseManager for async DB access.
        """
        self.accessor = accessor
        self.db_manager = db_manager
        # A dictionary to cache the configured logger instances for each provider.
        self._loggers: dict[str, logging.Logger] = {}
        self._setup_loggers()

    def _setup_loggers(self):
        """
        Dynamically configures individual loggers for each provider instance.
        This method uses RotatingFileHandler to manage log file size and backups
        based on the global logging configuration.
        """
        # REFACTORED: Use the accessor to get logging configuration.
        log_config = self.accessor.get_logging_config()
        log_dir = log_config.summary_log_path
        os.makedirs(log_dir, exist_ok=True)

        # REFACTORED: Use the accessor to iterate over all providers.
        for provider_name in self.accessor.get_all_providers():
            logger_name = f"summary.{provider_name}"

            if logger_name in self._loggers:
                continue

            l = logging.getLogger(logger_name)
            l.setLevel(logging.INFO)
            l.propagate = False

            handler = logging.handlers.RotatingFileHandler(
                filename=os.path.join(log_dir, f"{provider_name}.jsonl"),
                maxBytes=log_config.summary_log_max_size_mb * 1024 * 1024,
                backupCount=log_config.summary_log_backup_count,
                encoding="utf-8",
            )

            formatter = logging.Formatter("%(message)s")
            handler.setFormatter(formatter)

            if l.hasHandlers():
                l.handlers.clear()
            l.addHandler(handler)

            self._loggers[logger_name] = l
            module_logger.debug(
                f"Configured statistics logger for provider '{provider_name}'."
            )

    async def run_cycle(self):
        """
        Executes one full statistics gathering and logging cycle.
        This is the main async method called by the background scheduler.
        """
        module_logger.info("Starting statistics summary cycle...")

        try:
            # 1. Fetch aggregated data from the database asynchronously.
            summary_data = await self.db_manager.keys.get_status_summary()
            if not summary_data:
                module_logger.info("No status summary data to log in this cycle.")
                return

            # 2. Group the data by provider for separate file logging.
            grouped_data = defaultdict(list)
            for record in summary_data:
                grouped_data[record["provider"]].append(record)

            timestamp = datetime.now(UTC).isoformat()

            # 3. Iterate and log data for each provider.
            for provider_name, records in grouped_data.items():
                logger_name = f"summary.{provider_name}"
                summary_logger = self._loggers.get(logger_name)

                if not summary_logger:
                    module_logger.warning(
                        f"No configured logger found for provider '{provider_name}'. "
                        "This can happen if the provider was added to the config after startup. "
                        "Re-running setup."
                    )
                    self._setup_loggers()
                    summary_logger = self._loggers.get(logger_name)
                    if not summary_logger:
                        module_logger.error(
                            f"Failed to setup logger for '{provider_name}'. Skipping."
                        )
                        continue

                for record in records:
                    log_entry = {
                        "timestamp": timestamp,
                        "provider": record["provider"],
                        "model": record["model"],
                        "status": record["status"],
                        "count": record["count"],
                    }
                    # Log the JSON string. The handler will write it to the correct file.
                    summary_logger.info(json.dumps(log_entry))

            module_logger.info(
                f"Successfully logged statistics for {len(grouped_data)} providers."
            )

        except Exception:
            module_logger.critical(
                "A critical error occurred in the statistics logger cycle.",
                exc_info=True,
            )

        module_logger.info("Statistics summary cycle finished.")
