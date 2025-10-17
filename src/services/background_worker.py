# src/services/background_worker.py

import logging
import os
import asyncio
import asyncpg

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from src.config.loader import load_config
from src.config.logging_config import setup_logging
from src.config.schemas import Config
from src.db import database
from src.db.database import DatabaseManager
from src.core.http_client_factory import HttpClientFactory
from src.services.probes import get_all_probes
from src.services.synchronizers import get_all_syncers
from src.services.statistics_logger import StatisticsLogger
from src.services import maintenance

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
    logger: logging.Logger | None = None
    config: Config | None = None
    client_factory: HttpClientFactory | None = None
    
    try:
        # Step 1: Load Configuration
        config = load_config(CONFIG_PATH)

        # Step 2: Setup Centralized Logging
        setup_logging(config)
        logger = logging.getLogger(__name__)

        logger.info("--- Starting LLM Gateway Background Worker (Async) ---")
        
        # Step 3: Setup Directories
        _setup_directories(config)

        # Step 4: Initialize and Verify Database Connection
        dsn = config.database.to_dsn()
        await database.init_db_pool(dsn)
        db_manager = DatabaseManager(config)
        await db_manager.initialize_schema()
        
        # Step 5: Create Long-Lived Client Factory
        client_factory = HttpClientFactory(config)
        logger.info("Long-lived HttpClientFactory created.")

        # Step 6: Initial Resource Synchronization
        await db_manager.providers.sync(list(config.providers.keys()))
        all_syncers = get_all_syncers()
        for syncer in all_syncers:
            await syncer.sync(config, db_manager)
        
        logger.info("Initial resource synchronization finished.")

        # Step 7: Instantiate Services with Dependencies
        all_probes = get_all_probes(config, db_manager, client_factory)
        stats_logger = StatisticsLogger(config, db_manager)

        # Step 8: Scheduler Setup
        scheduler = AsyncIOScheduler(timezone="UTC")
        
        for i, probe in enumerate(all_probes):
            job_id = f"{probe.__class__.__name__}_cycle_{i}"
            scheduler.add_job(probe.run_cycle, 'interval', minutes=1, id=job_id)

        for i, syncer in enumerate(all_syncers):
            job_id = f"{syncer.__class__.__name__}_cycle_{i}"
            scheduler.add_job(syncer.sync, 'interval', minutes=5, args=[config, db_manager], id=job_id)
        
        scheduler.add_job(stats_logger.run_cycle, 'interval', minutes=config.logging.summary_interval_min)

        # --- REFACTORED: Pass the 'config' object to the amnesty task ---
        # This is the crucial change that enables the maintenance service to perform
        # "smart" amnesty based on provider-specific policies.
        scheduler.add_job(maintenance.run_periodic_amnesty, 'cron', hour=4, minute=0, args=[db_manager, config])
        scheduler.add_job(maintenance.run_periodic_vacuum, 'cron', day_of_week='sun', hour=5, minute=0, args=[db_manager])

        logger.info("Scheduler configured. List of jobs:")
        scheduler.print_jobs()
        
        # Step 9: Start Scheduler and Run Indefinitely
        scheduler.start()
        
        while True:
            await asyncio.sleep(3600)

    except (KeyboardInterrupt, SystemExit):
        if logger:
            logger.info("Shutdown signal received.")

    except asyncpg.exceptions.InvalidPasswordError:
        # This block correctly handles DB auth errors during initialization.
        if logger and config:
            db_conf = config.database
            logger.critical(
                f"Database authentication failed for user '{db_conf.user}'. "
                f"Please verify credentials in your .env file and config/providers.yaml."
            )
        else:
            print("[CRITICAL] Database authentication failed. Check credentials.")

    except (ConnectionRefusedError, OSError):
        # This block correctly handles DB connection errors during initialization.
        if logger and config:
            db_conf = config.database
            logger.critical(
                f"Could not connect to the database at {db_conf.host}:{db_conf.port}. "
                f"Please ensure the database server is running and accessible."
            )
        else:
            print("[CRITICAL] Could not connect to the database.")

    except Exception as e:
        if logger:
            logger.critical(f"A critical error occurred during worker setup or runtime: {e}", exc_info=True)
        else:
            print(f"[CRITICAL] A critical error occurred before logging was configured: {e}")
    finally:
        # Step 10: Graceful Shutdown
        shutdown_logger = logging.getLogger(__name__)

        shutdown_logger.info("Initiating graceful shutdown...")
        if scheduler and scheduler.running:
            scheduler.shutdown()
            shutdown_logger.info("Scheduler shut down.")

        if client_factory:
            await client_factory.close_all()
        
        await database.close_db_pool()
        shutdown_logger.info("Worker has been shut down gracefully.")
