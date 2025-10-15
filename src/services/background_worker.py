# src/services/background_worker.py

import logging

from apscheduler.schedulers.blocking import BlockingScheduler

# --- Centralized Configuration and Service Imports ---
from src.config.loader import load_config
from src.config.logging_config import setup_logging
from src.db import database
from src.services.probes import get_all_probes # Use factory instead of direct import
from src.services.synchronizers import get_all_syncers # Use factory
from src.services.statistics_logger import StatisticsLogger
from src.services import maintenance

# --- Constants ---
# These paths are centralized for easy modification.
# For production environments, consider sourcing these from environment variables.
DB_PATH = "data/llm_gateway.db"
CONFIG_PATH = "config/providers.yaml"


def run_worker():
    """
    The main function for the background worker service.
    
    This function orchestrates all background tasks, including resource synchronization,
    health probes, and database maintenance, using a scheduler.
    """

    # --- Step 1: Load Configuration ---
    # This is the first and most critical step. If config fails, nothing else can run.
    try:
        config = load_config(CONFIG_PATH)
    except Exception as e:
        # Use a basic print here because logging is not yet configured.
        print(f"[CRITICAL] Configuration failed to load from '{CONFIG_PATH}': {e}")
        return

    # --- Step 2: Setup Centralized Logging ---
    # Once the config is loaded, we can set up logging for the rest of the application.
    setup_logging(config)
    logger = logging.getLogger(__name__)

    logger.info("--- Starting LLM Gateway Background Worker ---")
    logger.info(f"Loaded configuration from '{CONFIG_PATH}'. Debug mode: {config.debug}")

    # --- Step 3: Initialize Database Schema ---
    # Ensure all tables and indexes exist before any operations are performed.
    logger.info(f"Initializing database schema at '{DB_PATH}'...")
    database.initialize_database(DB_PATH)

    # --- Step 4: Synchronize Providers ---
    # CRITICAL FIX for race condition: Populate the 'providers' table before syncing
    # any resources that depend on it (keys, proxies).
    logger.info("Synchronizing providers from config to database...")
    try:
        provider_names = list(config.providers.keys())
        database.sync_providers(DB_PATH, provider_names)
    except Exception as e:
        logger.critical(f"Failed to synchronize providers with the database: {e}", exc_info=True)
        return

    # --- Step 5: Initial Resource Synchronization ---
    # Use the syncer factory to run all available synchronizers.
    # This approach is modular and extensible.
    logger.info("Performing initial synchronization of all resources...")
    all_syncers = get_all_syncers()
    if not all_syncers:
        logger.warning("No resource synchronizers were found or initialized.")
    else:
        for syncer in all_syncers:
            syncer_name = syncer.__class__.__name__
            try:
                logger.info(f"Running initial sync with {syncer_name}...")
                syncer.sync(config, DB_PATH)
            except Exception as e:
                # Isolate failures: one failing syncer should not stop the worker from starting.
                logger.error(f"An error occurred during initial sync with {syncer_name}: {e}", exc_info=True)
    logger.info("Initial resource synchronization finished.")

    # --- Step 6: Scheduler Setup ---
    logger.info("Configuring and starting the scheduler...")
    scheduler = BlockingScheduler(timezone="UTC")

    # Instantiate services needed for scheduled jobs
    stats_logger = StatisticsLogger(config, DB_PATH)

    # --- Step 7: Add Jobs to Scheduler ---
    
    # Add all probe cycles using the probe factory
    all_probes = get_all_probes(config, DB_PATH)
    if not all_probes:
        logger.warning("No resource probes were found. Health checks will not run.")
    else:
        for i, probe in enumerate(all_probes):
            probe_name = probe.__class__.__name__
            job_id = f"{probe_name}_cycle_{i}"
            scheduler.add_job(probe.run_cycle, 'interval', minutes=1, id=job_id)
            logger.info(f"Scheduled job: {probe_name} to run every 1 minute.")

    # Add all sync cycles using the syncer factory
    for i, syncer in enumerate(all_syncers):
        syncer_name = syncer.__class__.__name__
        job_id = f"{syncer_name}_cycle_{i}"
        scheduler.add_job(syncer.sync, 'interval', minutes=5, args=[config, DB_PATH], id=job_id)
        logger.info(f"Scheduled job: {syncer_name} to run every 5 minutes.")
    
    # Add the statistics logger job
    scheduler.add_job(
        stats_logger.run_cycle, 
        'interval', 
        minutes=config.logging.summary_interval_min, 
        id='statistics_summary_cycle'
    )
    logger.info(f"Scheduled job: StatisticsLogger to run every {config.logging.summary_interval_min} minutes.")

    # Add maintenance jobs
    scheduler.add_job(maintenance.run_periodic_amnesty, 'cron', hour=4, minute=0, args=[DB_PATH], id='amnesty_dead_keys')
    scheduler.add_job(maintenance.run_periodic_vacuum, 'cron', day_of_week='sun', hour=5, minute=0, args=[DB_PATH], id='vacuum_database')
    logger.info("Scheduled maintenance jobs (amnesty and vacuum).")

    logger.info("Scheduler configured. List of jobs:")
    scheduler.print_jobs()
    
    try:
        # --- Step 8: Start the Scheduler ---
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Scheduler stopped by user. Shutting down...")
    except Exception as e:
        logger.critical(f"A critical error occurred in the scheduler: {e}", exc_info=True)
    finally:
        if scheduler.running:
            scheduler.shutdown()

