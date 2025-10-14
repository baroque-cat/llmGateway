# /llmGateway/background_worker.py

import logging
import time

from apscheduler.schedulers.blocking import BlockingScheduler

# --- Centralized Configuration and Service Imports ---
# It's better to import specific functions and classes for clarity.
from src.config.loader import load_config
from src.config.logging_config import setup_logging # Using the centralized logging setup
from src.db import database
from src.services.probes.key_probe import KeyProbe
from src.services.synchronizers.key_sync import KeySyncer
from src.services.synchronizers.proxy_sync import ProxySyncer
from src.services import maintenance

# --- Constants ---
# Centralize constants for easy modification.
DB_PATH = "data/llm_gateway.db"
CONFIG_PATH = "config/providers.yaml"


def main():
    """
    The main entry point for the background worker service.
    
    This script orchestrates all background tasks, including resource synchronization,
    health probes, and database maintenance, using a scheduler.
    
    NOTE: To run this script correctly from the project root, use:
    python -m llmGateway.background_worker
    This ensures all relative imports within the 'src' package work as expected.
    """

    # --- Step 1: Load Configuration ---
    # Configuration must be loaded first, as it dictates behavior for all other modules,
    # including the logging level.
    try:
        config = load_config(CONFIG_PATH)
    except (ValueError, FileNotFoundError) as e:
        # Use basic print for this critical failure, as logging might not be configured yet.
        print(f"[CRITICAL] Configuration error: {e}")
        return

    # --- Step 2: Setup Centralized Logging ---
    # Now that we have the config, we can set up logging for the entire application.
    # The logging level (DEBUG/INFO) will be determined by the 'debug' flag in the config.
    setup_logging(config)
    logger = logging.getLogger(__name__)

    logger.info("--- Starting LLM Gateway Background Worker ---")
    logger.info(f"Loaded configuration from '{CONFIG_PATH}'. Debug mode: {config.debug}")

    # --- Step 3: Initialize Database ---
    logger.info(f"Initializing database at '{DB_PATH}'...")
    database.initialize_database(DB_PATH)

    # --- Step 4: Initial Resource Synchronization ---
    # This ensures the database is up-to-date with files on disk before any probes run.
    logger.info("Performing initial synchronization of all resources...")
    try:
        KeySyncer().sync(config, DB_PATH)
        ProxySyncer().sync(config, DB_PATH) # This will log warnings until the DB part is done
        logger.info("Initial synchronization completed successfully.")
    except Exception as e:
        logger.critical(f"An error occurred during initial synchronization: {e}", exc_info=True)
        return

    # --- Step 5: Scheduler Setup ---
    logger.info("Configuring and starting the scheduler...")
    scheduler = BlockingScheduler()

    # Instantiate services needed for scheduled jobs
    key_probe = KeyProbe(config, DB_PATH)
    key_syncer = KeySyncer()
    proxy_syncer = ProxySyncer()

    # --- Step 6: Add Jobs to Scheduler ---
    scheduler.add_job(key_probe.run_cycle, 'interval', minutes=1, id='key_probe_cycle')
    scheduler.add_job(key_syncer.sync, 'interval', minutes=5, args=[config, DB_PATH], id='key_sync_cycle')
    scheduler.add_job(proxy_syncer.sync, 'interval', minutes=5, args=[config, DB_PATH], id='proxy_sync_cycle')
    scheduler.add_job(maintenance.run_periodic_amnesty, 'cron', hour=4, minute=0, args=[DB_PATH], id='amnesty_dead_keys')
    scheduler.add_job(maintenance.run_periodic_vacuum, 'cron', day_of_week='sun', hour=5, minute=0, args=[DB_PATH], id='vacuum_database')

    logger.info("Scheduler configured. List of jobs:")
    scheduler.print_jobs() # This method from apscheduler prints directly to stdout, which is acceptable for startup info.
    
    try:
        # --- Step 7: Start the Scheduler ---
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Scheduler stopped by user. Shutting down...")
    except Exception as e:
        logger.critical(f"A critical error occurred in the scheduler: {e}", exc_info=True)
    finally:
        if scheduler.running:
            scheduler.shutdown()

if __name__ == '__main__':
    main()
