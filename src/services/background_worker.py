# src/services/background_worker.py

import logging
import os
import asyncio
import httpx
import asyncpg # --- ADDED: Import for specific exception handling ---

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from src.config.loader import load_config
from src.config.logging_config import setup_logging
from src.config.schemas import Config
from src.db import database
from src.db.database import DatabaseManager
from src.services.probes import get_all_probes
from src.services.synchronizers import get_all_syncers
from src.services.statistics_logger import StatisticsLogger
from src.services import maintenance

# This path is now only used as a default for the config loader.
CONFIG_PATH = "config/providers.yaml"

def _setup_directories(config: Config):
    """
    Ensures that all necessary directories specified in the config exist.
    Creates them if they don't.
    """
    logger = logging.getLogger(__name__)
    logger.info("Checking and setting up required directories...")
    
    paths_to_check = {
        config.logging.summary_log_path,
    }
    
    for provider in config.providers.values():
        if provider.enabled:
            if provider.keys_path:
                paths_to_check.add(provider.keys_path)
            if provider.proxy_config.mode == 'stealth' and provider.proxy_config.pool_list_path:
                paths_to_check.add(provider.proxy_config.pool_list_path)

    try:
        for path in paths_to_check:
            if path:
                os.makedirs(path, exist_ok=True)
                logger.debug(f"Directory ensured: '{path}'")
        logger.info("Directory setup complete.")
    except PermissionError as e:
        logger.critical(f"Permission denied while creating directory: {e}. Please check file system permissions.")
        raise
    except Exception as e:
        logger.critical(f"An unexpected error occurred during directory setup: {e}")
        raise

async def run_worker():
    """
    The main async function for the background worker service.
    Orchestrates all background tasks in a non-blocking manner.
    """
    scheduler = None
    # --- MODIFIED: Assign logger and config to None initially ---
    # This makes the exception handling more robust, as we can check if they were assigned
    # before the exception occurred.
    logger: logging.Logger | None = None
    config: Config | None = None
    try:
        # --- Step 1: Load Configuration ---
        config = load_config(CONFIG_PATH)

        # --- Step 2: Setup Centralized Logging ---
        setup_logging(config)
        logger = logging.getLogger(__name__)

        logger.info("--- Starting LLM Gateway Background Worker (Async) ---")
        
        # --- Step 3: Setup Directories ---
        _setup_directories(config)

        # --- Step 4: Initialize and Verify Database Connection ---
        dsn = config.database.to_dsn()
        await database.init_db_pool(dsn)
        db_manager = DatabaseManager(config)
        
        # This check is now less critical because of the specific exception handling below,
        # but it's good practice to keep it as a general health check.
        # It was removed from database.py in a previous step, so we will remove the call.
        # if not await db_manager.check_connection():
        #     raise ConnectionError("Could not establish a valid connection to the database.")
        
        await db_manager.initialize_schema()
        
        # --- Step 5: Create Long-Lived HTTP Client ---
        async with httpx.AsyncClient(timeout=30.0) as http_client:
            logger.info("Long-lived HTTPX client created.")

            # --- Step 6: Initial Resource Synchronization ---
            await db_manager.providers.sync(list(config.providers.keys()))
            all_syncers = get_all_syncers()
            for syncer in all_syncers:
                await syncer.sync(config, db_manager)
            
            logger.info("Initial resource synchronization finished.")

            # --- Step 7: Instantiate Services with Dependencies ---
            all_probes = get_all_probes(config, db_manager, http_client)
            stats_logger = StatisticsLogger(config, db_manager)

            # --- Step 8: Scheduler Setup ---
            scheduler = AsyncIOScheduler(timezone="UTC")
            
            # Add probe jobs
            for i, probe in enumerate(all_probes):
                job_id = f"{probe.__class__.__name__}_cycle_{i}"
                scheduler.add_job(probe.run_cycle, 'interval', minutes=1, id=job_id)

            # Add sync jobs
            for i, syncer in enumerate(all_syncers):
                job_id = f"{syncer.__class__.__name__}_cycle_{i}"
                scheduler.add_job(syncer.sync, 'interval', minutes=5, args=[config, db_manager], id=job_id)
            
            # Add statistics logger job
            scheduler.add_job(stats_logger.run_cycle, 'interval', minutes=config.logging.summary_interval_min)

            # Add maintenance jobs
            scheduler.add_job(maintenance.run_periodic_amnesty, 'cron', hour=4, minute=0, args=[db_manager])
            scheduler.add_job(maintenance.run_periodic_vacuum, 'cron', day_of_week='sun', hour=5, minute=0, args=[db_manager])

            logger.info("Scheduler configured. List of jobs:")
            scheduler.print_jobs()
            
            # --- Step 9: Start Scheduler and Run Indefinitely ---
            scheduler.start()
            
            # This loop keeps the main coroutine alive.
            while True:
                await asyncio.sleep(3600)

    except (KeyboardInterrupt, SystemExit):
        if logger:
            logger.info("Shutdown signal received.")

    # --- NEW: Specific exception handler for authentication errors ---
    except asyncpg.exceptions.InvalidPasswordError:
        if logger and config:
            db_conf = config.database
            logger.critical(
                f"Database authentication failed for user '{db_conf.user}'. "
                f"Please verify that DB_USER, DB_PASSWORD, and other connection settings "
                f"in your .env file and config/providers.yaml are correct for the database at "
                f"{db_conf.host}:{db_conf.port}."
            )
        else:
            print("[CRITICAL] Database authentication failed. Check credentials in .env and config.")

    # --- NEW: Specific exception handler for connection errors ---
    except (ConnectionRefusedError, OSError):
        if logger and config:
            db_conf = config.database
            logger.critical(
                f"Could not connect to the database at {db_conf.host}:{db_conf.port}. "
                f"Please ensure the database server is running, accessible, and that "
                f"the host and port in config/providers.yaml are correct."
            )
        else:
            print("[CRITICAL] Could not connect to the database. Check connection settings and server status.")

    except Exception as e:
        # Catch exceptions during the critical setup phase.
        if logger:
            logger.critical(f"A critical error occurred during worker setup or runtime: {e}", exc_info=True)
        else:
            # Fallback to print if logging is not configured.
            print(f"[CRITICAL] A critical error occurred before logging was configured: {e}")
    finally:
        # --- Step 10: Graceful Shutdown ---
        # Get a logger instance. If setup failed, this creates a default one.
        shutdown_logger = logging.getLogger(__name__)

        shutdown_logger.info("Initiating graceful shutdown...")
        if scheduler and scheduler.running:
            scheduler.shutdown()
            shutdown_logger.info("Scheduler shut down.")
        
        await database.close_db_pool()
        # httpx.AsyncClient is closed automatically by the 'async with' statement.
        shutdown_logger.info("Worker has been shut down gracefully.")

