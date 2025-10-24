# src/services/background_worker.py

import logging
import os
import asyncio
import asyncpg
from typing import List, Dict

from apscheduler.schedulers.asyncio import AsyncIOScheduler

# Import the new centralized package entry point and key components.
from src.config import load_config
from src.config.logging_config import setup_logging
from src.core.accessor import ConfigAccessor
from src.core.types import IResourceSyncer, ProviderKeyState, ProviderProxyState
from src.db import database
from src.db.database import DatabaseManager
from src.core.http_client_factory import HttpClientFactory
from src.services.probes import get_all_probes
from src.services.synchronizers import get_all_syncers
# REFACTORED: Import helper functions directly for the Read Phase.
from src.services.synchronizers.key_sync import _read_keys_from_directory
from src.services.synchronizers.proxy_sync import _read_proxies_from_directory
from src.services.statistics_logger import StatisticsLogger
from src.services import maintenance

# The path is now defined in one place and passed to the loader.
CONFIG_PATH = "config/providers.yaml"

def _setup_directories(accessor: ConfigAccessor):
    """
    Ensures that all necessary directories specified in the config exist.
    Creates them if they don't, using the ConfigAccessor.
    """
    logger = logging.getLogger(__name__)
    logger.info("Checking and setting up required directories...")
    
    paths_to_check = {
        accessor.get_logging_config().summary_log_path,
    }
    
    for provider in accessor.get_all_providers().values():
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


# --- NEW: Two-Phase Synchronization Cycle ---
async def run_sync_cycle(accessor: ConfigAccessor, db_manager: DatabaseManager, all_syncers: List[IResourceSyncer]):
    """
    Orchestrates a single, two-phase synchronization cycle.
    This function centralizes the synchronization logic, making it more robust and readable.
    """
    logger = logging.getLogger(__name__)
    logger.info("Starting new TWO-PHASE synchronization cycle...")

    try:
        # --- PHASE 1: READ ---
        # Collect the complete "desired state" from configuration and files without touching the database.
        logger.info("Sync Phase 1 (Read): Collecting desired state from files and config...")
        desired_state: Dict[str, Dict] = {
            "keys": {},
            "proxies": {}
        }

        enabled_providers = accessor.get_enabled_providers()
        for provider_name, provider_config in enabled_providers.items():
            # For KeySyncer (always runs for enabled providers)
            keys_from_file = _read_keys_from_directory(provider_config.keys_path)
            models_from_config = list(provider_config.models.keys())
            key_state: ProviderKeyState = {'keys_from_files': keys_from_file, 'models_from_config': models_from_config}
            desired_state["keys"][provider_name] = key_state

            # For ProxySyncer (runs only if mode is 'stealth')
            if provider_config.proxy_config.mode == 'stealth':
                proxies_from_file = _read_proxies_from_directory(provider_config.proxy_config.pool_list_path)
                proxy_state: ProviderProxyState = {'proxies_from_files': proxies_from_file}
                desired_state["proxies"][provider_name] = proxy_state
        
        logger.info(f"Sync Phase 1 (Read) complete. Collected state for {len(enabled_providers)} providers.")

        # --- PHASE 2: APPLY ---
        # Apply the collected desired state to the database using the synchronizers.
        logger.info("Sync Phase 2 (Apply): Applying collected state to the database...")
        
        provider_id_map = await db_manager.providers.get_id_map()

        # Polymorphically call the 'apply_state' method on each syncer.
        for syncer in all_syncers:
            syncer_name = syncer.__class__.__name__
            try:
                if isinstance(syncer, from_services_synchronizers_key_sync_import_KeySyncer):
                    await syncer.apply_state(provider_id_map, desired_state["keys"])
                elif isinstance(syncer, from_services_synchronizers_proxy_sync_import_ProxySyncer):
                    await syncer.apply_state(provider_id_map, desired_state["proxies"])
            except Exception as e:
                 logger.error(f"Error during apply phase for {syncer_name}: {e}", exc_info=True)
        
        logger.info("Sync Phase 2 (Apply) complete. Database state is consistent.")

    except Exception as e:
        logger.critical(f"A critical error occurred during the synchronization cycle: {e}", exc_info=True)

    logger.info("Synchronization cycle finished.")


async def run_worker():
    """
    The main async function for the background worker service.
    Orchestrates all background tasks using the new accessor-based architecture.
    """
    scheduler = None
    logger: logging.Logger | None = None
    client_factory: HttpClientFactory | None = None
    
    try:
        # Step 1: Load Configuration and create the Accessor.
        config = load_config(CONFIG_PATH)
        accessor = ConfigAccessor(config)

        # Step 2: Setup Centralized Logging.
        setup_logging(accessor)
        logger = logging.getLogger(__name__)

        logger.info("--- Starting LLM Gateway Background Worker (Async) ---")
        
        # Step 3: Setup Directories.
        _setup_directories(accessor)

        # Step 4: Initialize and Verify Database Connection.
        dsn = accessor.get_database_dsn()
        await database.init_db_pool(dsn)
        db_manager = DatabaseManager(accessor)
        await db_manager.initialize_schema()
        
        # Step 5: Create Long-Lived Client Factory.
        client_factory = HttpClientFactory(accessor)
        logger.info("Long-lived HttpClientFactory created.")

        # Step 6: Initial Resource Synchronization.
        # This part is now refactored to use the new two-phase cycle function.
        logger.info("Performing initial resource synchronization...")
        await db_manager.providers.sync(list(accessor.get_all_providers().keys()))
        all_syncers = get_all_syncers(accessor, db_manager)
        await run_sync_cycle(accessor, db_manager, all_syncers)
        logger.info("Initial resource synchronization finished.")

        # Step 7: Instantiate Services with Dependencies.
        all_probes = get_all_probes(accessor, db_manager, client_factory)
        stats_logger = StatisticsLogger(accessor, db_manager)

        # Step 8: Scheduler Setup.
        scheduler = AsyncIOScheduler(timezone="UTC")
        
        for i, probe in enumerate(all_probes):
            job_id = f"{probe.__class__.__name__}_cycle_{i}"
            scheduler.add_job(probe.run_cycle, 'interval', minutes=1, id=job_id)

        # REFACTORED: Instead of scheduling each syncer, schedule the central cycle function.
        scheduler.add_job(
            run_sync_cycle, 
            'interval', 
            minutes=5, 
            id="two_phase_sync_cycle",
            args=[accessor, db_manager, all_syncers] # Pass dependencies to the scheduled job.
        )
        
        summary_interval = accessor.get_logging_config().summary_interval_min
        scheduler.add_job(stats_logger.run_cycle, 'interval', minutes=summary_interval)

        scheduler.add_job(maintenance.run_periodic_vacuum, 'cron', day_of_week='sun', hour=5, minute=0, args=[db_manager])

        logger.info("Scheduler configured. List of jobs:")
        scheduler.print_jobs()
        
        # Step 9: Start Scheduler and Run Indefinitely
        scheduler.start()
        
        # This loop keeps the main coroutine alive.
        while True:
            await asyncio.sleep(3600)

    except (KeyboardInterrupt, SystemExit):
        if logger:
            logger.info("Shutdown signal received.")
    except asyncpg.exceptions.InvalidPasswordError:
        # Error logging for specific, common setup problems.
        db_conf = ConfigAccessor(load_config(CONFIG_PATH)).get_database_config()
        print(
            f"[CRITICAL] Database authentication failed for user '{db_conf.user}'. "
            f"Please verify credentials in your .env file."
        )
    except (ConnectionRefusedError, OSError) as e:
        db_conf = ConfigAccessor(load_config(CONFIG_PATH)).get_database_config()
        print(
            f"[CRITICAL] Could not connect to the database at {db_conf.host}:{db_conf.port}. "
            f"Error: {e}. Please ensure the database server is running and accessible."
        )
    except Exception as e:
        if logger:
            logger.critical(f"A critical error occurred during worker setup or runtime: {e}", exc_info=True)
        else:
            print(f"[CRITICAL] A critical error occurred before logging was configured: {e}")
    finally:
        # Step 10: Graceful Shutdown
        shutdown_logger = logging.getLogger(__name__) or logging.getLogger("shutdown")
        shutdown_logger.info("Initiating graceful shutdown...")
        if scheduler and scheduler.running:
            scheduler.shutdown()
            shutdown_logger.info("Scheduler shut down.")

        if client_factory:
            await client_factory.close_all()
        
        await database.close_db_pool()
        shutdown_logger.info("Worker has been shut down gracefully.")


# A workaround for isinstance check within the function due to Python's import system.
# This makes the code inside run_sync_cycle a bit cleaner.
from src.services.synchronizers.key_sync import KeySyncer as from_services_synchronizers_key_sync_import_KeySyncer
from src.services.synchronizers.proxy_sync import ProxySyncer as from_services_synchronizers_proxy_sync_import_ProxySyncer
