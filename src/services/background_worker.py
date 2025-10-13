# /llmGateway/background_worker.py

import logging
import sys
import time

# Ensure the 'src' directory is in the Python path
# This is a common pattern for running scripts from the project root
sys.path.append('src')

from apscheduler.schedulers.blocking import BlockingScheduler

from src.config.loader import load_config
from src.db import database
from src.services.probes.key_probe import KeyProbe
from src.services.synchronizers.key_sync import KeySyncer
from src.services.synchronizers.proxy_sync import ProxySyncer
from src.services import maintenance

# --- Constants ---
DB_PATH = "data/llm_gateway.db"
CONFIG_PATH = "config/providers.yaml"


def setup_logging():
    """
    Configures basic logging for the application.
    Logs will be printed to the console with a clear format.
    """
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - [%(levelname)s] - %(message)s',
        stream=sys.stdout
    )
    # Set a lower level for apscheduler to reduce noise
    logging.getLogger('apscheduler.executors.default').setLevel(logging.WARNING)


def main():
    """
    The main entry point for the background worker service.
    """
    setup_logging()
    logger = logging.getLogger(__name__)

    logger.info("--- Starting LLM Gateway Background Worker ---")

    # --- Step 1: Initialization ---
    logger.info(f"Loading configuration from '{CONFIG_PATH}'...")
    try:
        config = load_config(CONFIG_PATH)
    except ValueError as e:
        logger.critical(f"Configuration error: {e}")
        return  # Exit if config is invalid

    logger.info(f"Initializing database at '{DB_PATH}'...")
    database.initialize_database(DB_PATH)

    # --- Step 2: Initial Resource Synchronization ---
    # It's crucial to perform an initial sync before starting the scheduled probes.
    # This ensures the database is populated with the latest keys and proxies from files.
    logger.info("Performing initial synchronization of all resources...")
    try:
        KeySyncer().sync(config, DB_PATH)
        ProxySyncer().sync(config, DB_PATH)
        logger.info("Initial synchronization completed successfully.")
    except Exception as e:
        logger.critical(f"An error occurred during initial synchronization: {e}", exc_info=True)
        return # Do not proceed if the initial sync fails

    # --- Step 3: Scheduler Setup ---
    logger.info("Configuring and starting the scheduler...")
    scheduler = BlockingScheduler()

    # Instantiate all service classes that will be used in scheduled jobs
    key_probe = KeyProbe(config, DB_PATH)
    key_syncer = KeySyncer()
    proxy_syncer = ProxySyncer()

    # --- Step 4: Add Jobs to Scheduler ---
    # Add jobs with different intervals based on their purpose.
    
    # High-frequency job: Check keys that are due.
    scheduler.add_job(key_probe.run_cycle, 'interval', minutes=1, id='key_probe_cycle')
    
    # Medium-frequency jobs: Sync resources from files.
    scheduler.add_job(key_syncer.sync, 'interval', minutes=5, args=[config, DB_PATH], id='key_sync_cycle')
    scheduler.add_job(proxy_syncer.sync, 'interval', minutes=5, args=[config, DB_PATH], id='proxy_sync_cycle')
    
    # Low-frequency jobs: Database maintenance.
    scheduler.add_job(maintenance.run_periodic_amnesty, 'cron', hour=4, minute=0, args=[DB_PATH], id='amnesty_dead_keys')
    scheduler.add_job(maintenance.run_periodic_vacuum, 'cron', day_of_week='sun', hour=5, minute=0, args=[DB_PATH], id='vacuum_database')

    logger.info("Scheduler configured. List of jobs:")
    scheduler.print_jobs()
    
    try:
        # --- Step 5: Start the Scheduler ---
        # This is a blocking call that will run indefinitely.
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Scheduler stopped. Shutting down...")
        scheduler.shutdown()
    except Exception as e:
        logger.critical(f"A critical error occurred in the scheduler: {e}", exc_info=True)


if __name__ == '__main__':
    main()

