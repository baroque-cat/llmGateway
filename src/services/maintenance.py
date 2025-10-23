# src/services/maintenance.py

import logging
from src.db.database import DatabaseManager
# REFACTORED: Import ConfigAccessor instead of Config.
from src.core.accessor import ConfigAccessor

# Initialize a logger for this module.
# The output will be handled by the central logging configuration.
logger = logging.getLogger(__name__)

# REFACTORED: The function now accepts ConfigAccessor to implement smart amnesty.
async def run_periodic_amnesty(db_manager: DatabaseManager, accessor: ConfigAccessor):
    """
    Service-level task to grant amnesty to 'dead' keys based on provider-specific policies.
    This function is intended to be called periodically by the background worker.

    Args:
        db_manager: An instance of the DatabaseManager for async DB access.
        accessor: An instance of ConfigAccessor, used to get amnesty policies.
    """
    logger.info("SERVICE: Running periodic task: Smart Amnesty for dead keys.")
    try:
        # REFACTORED: Iterate through providers using the accessor.
        # get_all_providers() is used here because we want to check all configured
        # providers, but the internal logic already skips disabled ones.
        for provider_name, provider_config in accessor.get_all_providers().items():
            if not provider_config.enabled:
                logger.debug(f"Skipping amnesty for disabled provider '{provider_name}'.")
                continue

            try:
                # Get the specific amnesty period for this provider from its health policy.
                amnesty_days = provider_config.health_policy.on_invalid_key_days
                
                # Call the database method that handles the time-based logic.
                await db_manager.run_amnesty(
                    provider_name=provider_name,
                    amnesty_days=amnesty_days
                )
            except Exception as e:
                # Isolate failures: an error with one provider should not stop the process for others.
                logger.error(
                    f"An error occurred during the amnesty task for provider '{provider_name}'.",
                    exc_info=e
                )
    except Exception as e:
        logger.critical("A critical error occurred during the main amnesty maintenance task.", exc_info=e)


async def run_periodic_vacuum(db_manager: DatabaseManager):
    """
    Service-level task to perform a VACUUM operation on the database (Async Version).
    In PostgreSQL, this complements the autovacuum daemon.
    This function should be called infrequently (e.g., weekly).

    Args:
        db_manager: An instance of the DatabaseManager for async DB access.
    """
    logger.info("SERVICE: Running periodic task: Database VACUUM.")
    try:
        await db_manager.run_vacuum()
    except Exception as e:
        logger.error("An error occurred during the VACUUM maintenance task.", exc_info=e)
