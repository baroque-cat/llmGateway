# src/services/keeper.py

import asyncio
import logging
import os
from collections.abc import Callable
from typing import Any, cast

import asyncpg
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

# Import the new centralized package entry point and key components.
from src.config import load_config
from src.config.logging_config import setup_logging
from src.core.accessor import ConfigAccessor
from src.core.http_client_factory import HttpClientFactory
from src.core.interfaces import IResourceSyncer, ProviderKeyState
from src.db import database
from src.db.database import DatabaseManager
from src.metrics import get_collector
from src.metrics.registry import (
    ADAPTIVE_BACKOFF_EVENTS,
    ADAPTIVE_BATCH_DELAY,
    ADAPTIVE_BATCH_SIZE,
    ADAPTIVE_RATE_LIMIT_EVENTS,
    ADAPTIVE_RECOVERY_EVENTS,
)
from src.services.db_maintainer import DatabaseMaintainer
from src.services.inventory_exporter import KeyInventoryExporter
from src.services.key_probe import get_all_probes
from src.services.key_purger import KeyPurger
from src.services.synchronizers import get_all_syncers
from src.services.synchronizers.key_sync import read_keys_from_directory

# The path is now defined in one place and passed to the loader.
CONFIG_PATH = "config/providers.yaml"


def _add_scheduler_job(
    scheduler: AsyncIOScheduler,
    func: Callable[..., Any],
    *args: Any,
    **kwargs: Any,
) -> None:
    """Wrapper for scheduler.add_job to avoid per-call type: ignore comments."""
    # fmt: off
    cast(None, scheduler.add_job(func, *args, **kwargs))  # pyright: ignore[reportUnknownMemberType]
    # fmt: on


def _setup_directories(accessor: ConfigAccessor) -> None:
    """
    Ensures that all necessary directories specified in the config exist.
    Creates them if they don't, using the ConfigAccessor.
    """
    logger = logging.getLogger(__name__)
    logger.info("Checking and setting up required directories...")

    paths_to_check: set[str] = set()

    for provider_name, provider in accessor.get_all_providers().items():
        if provider.enabled:
            key_path = os.path.join("data", provider_name, "raw")
            paths_to_check.add(key_path)

    try:
        for path in paths_to_check:
            if path:
                os.makedirs(path, exist_ok=True)
                logger.debug(f"Directory ensured: '{path}'")

        # Warn if any enabled provider's key directory has no key files
        for provider_name, provider in accessor.get_all_providers().items():
            if provider.enabled:
                key_path = os.path.join("data", provider_name, "raw")
                if os.path.isdir(key_path):
                    entries = os.listdir(key_path)
                    has_keys = any(
                        os.path.isfile(os.path.join(key_path, e))
                        and os.path.splitext(e)[1].lower() in (".txt", ".ndjson")
                        for e in entries
                    )
                    if not has_keys:
                        logger.warning(
                            f"No key files (.txt/.ndjson) found in '{key_path}'. "
                            f"Please place API keys in this directory."
                        )

        logger.info("Directory setup complete.")

        # --- Startup cleanup: remove leftover .trash/ directories ---
        # After a crash, raw key files may have been moved to .trash/ but not
        # yet unlinked. Clean those up now so they don't accumulate.
        for provider_name, provider in accessor.get_all_providers().items():
            if not provider.enabled:
                continue
            trash_dir = os.path.join("data", provider_name, "raw", ".trash")
            if os.path.isdir(trash_dir):
                try:
                    for entry in os.listdir(trash_dir):
                        entry_path = os.path.join(trash_dir, entry)
                        if os.path.isfile(entry_path) or os.path.islink(entry_path):
                            os.unlink(entry_path)
                    os.rmdir(trash_dir)
                    logger.info(
                        "Startup cleanup: removed leftover .trash/ for '%s'",
                        provider_name,
                    )
                except OSError as e:
                    logger.warning(
                        "Startup cleanup: could not fully clean .trash/ for '%s': %s",
                        provider_name,
                        e,
                    )

    except PermissionError as e:
        logger.critical(
            f"Permission denied while creating directory: {e}. Please check file system permissions."
        )
        raise
    except Exception as e:
        logger.critical(f"An unexpected error occurred during directory setup: {e}")
        raise


# --- NEW: Two-Phase Synchronization Cycle ---
async def run_sync_cycle(
    accessor: ConfigAccessor,
    db_manager: DatabaseManager,
    all_syncers: list[IResourceSyncer],
) -> None:
    """
    Orchestrates a single, two-phase synchronization cycle.
    This function centralizes the synchronization logic, making it more robust and readable.
    """
    logger = logging.getLogger(__name__)
    logger.debug("Starting new TWO-PHASE synchronization cycle...")

    try:
        # --- PHASE 1: READ ---
        # Collect the complete "desired state" from configuration and files without touching the database.
        logger.debug(
            "Sync Phase 1 (Read): Collecting desired state from files and config..."
        )
        desired_state: dict[str, dict[str, Any]] = {
            "keys": {},
        }

        enabled_providers = accessor.get_enabled_providers()
        for provider_name, provider_config in enabled_providers.items():
            # For KeySyncer (always runs for enabled providers)
            key_path = os.path.join("data", provider_name, "raw")
            keys_from_file, file_map = read_keys_from_directory(key_path)
            models_from_config = list(provider_config.models.keys())
            key_state: ProviderKeyState = {
                "keys_from_files": keys_from_file,
                "models_from_config": models_from_config,
                "file_map": file_map,
            }
            desired_state["keys"][provider_name] = key_state

        logger.debug(
            f"Sync Phase 1 (Read) complete. Collected state for {len(enabled_providers)} providers."
        )

        # --- PHASE 2: APPLY ---
        # Apply the collected desired state to the database using the synchronizers.
        logger.debug(
            "Sync Phase 2 (Apply): Applying collected state to the database..."
        )

        provider_id_map = await db_manager.providers.get_id_map()

        # Polymorphically call the 'apply_state' method on each syncer.
        for syncer in all_syncers:
            syncer_name = syncer.__class__.__name__
            try:
                # Get the specific part of the desired state that this syncer is responsible for.
                resource_type = syncer.get_resource_type()
                state_for_syncer = desired_state[resource_type]
                await syncer.apply_state(provider_id_map, state_for_syncer)
            except Exception as e:
                logger.error(
                    f"Error during apply phase for {syncer_name}: {e}", exc_info=True
                )

        logger.debug("Sync Phase 2 (Apply) complete. Database state is consistent.")

    except Exception as e:
        logger.critical(
            f"A critical error occurred during the synchronization cycle: {e}",
            exc_info=True,
        )

    logger.debug("Synchronization cycle finished.")


def _create_adaptive_metrics_callback() -> Callable[..., None]:
    """Create a callback that writes adaptive controller state to collector gauges.

    Returns a callable with the same signature as the old
    ``update_adaptive_controller_state``, but writes through the
    singleton ``IMetricsCollector`` instead of module-level Prometheus
    objects.
    """

    def _callback(
        provider_name: str,
        batch_size: int,
        batch_delay: float,
        rate_limit_events: int,
        backoff_events: int,
        recovery_events: int,
    ) -> None:
        collector = get_collector()

        collector.gauge(
            ADAPTIVE_BATCH_SIZE,
            "Current adaptive batch size per provider",
            ["provider"],
        ).set(float(batch_size), {"provider": provider_name})

        collector.gauge(
            ADAPTIVE_BATCH_DELAY,
            "Current adaptive batch delay in seconds per provider",
            ["provider"],
        ).set(batch_delay, {"provider": provider_name})

        collector.gauge(
            ADAPTIVE_RATE_LIMIT_EVENTS,
            "Total number of aggressive (rate-limit) backoff events per provider",
            ["provider"],
        ).set(float(rate_limit_events), {"provider": provider_name})

        collector.gauge(
            ADAPTIVE_BACKOFF_EVENTS,
            "Total number of moderate (transient-threshold) backoff events per provider",
            ["provider"],
        ).set(float(backoff_events), {"provider": provider_name})

        collector.gauge(
            ADAPTIVE_RECOVERY_EVENTS,
            "Total number of recovery (ramp-up) events per provider",
            ["provider"],
        ).set(float(recovery_events), {"provider": provider_name})

    return _callback


async def _start_metrics_server(logger: logging.Logger) -> None:
    """Start a minimal HTTP server for Prometheus /metrics on port 9090.

    Uses ``prometheus_client.make_asgi_app()`` + uvicorn to avoid
    pulling in FastAPI just for metrics export.
    """
    from prometheus_client import make_asgi_app  # type: ignore[reportUnknownVariableType]

    try:
        import uvicorn
    except ImportError:
        logger.error("uvicorn not available — Keeper /metrics endpoint disabled.")
        return

    metrics_app = make_asgi_app()  # pyright: ignore[reportUnknownVariableType]
    config = uvicorn.Config(
        metrics_app,  # pyright: ignore[reportUnknownArgumentType]
        host="0.0.0.0",
        port=9090,
        log_level="error",
    )
    server = uvicorn.Server(config)
    logger.info("Keeper /metrics endpoint starting on port 9090")
    await server.serve()


async def _collect_db_metrics_loop(
    db_manager: DatabaseManager, interval_sec: int = 30
) -> None:
    """Periodically collect DB-derived metrics via the collector.

    Runs inside the Keeper's asyncio event loop.
    """
    logger = logging.getLogger(__name__)
    while True:
        try:
            collector = get_collector()
            await collector.collect_from_db(db_manager)
        except asyncio.CancelledError:
            break
        except Exception:
            logger.error("Error collecting DB metrics", exc_info=True)
        await asyncio.sleep(interval_sec)


async def run_keeper() -> None:
    """
    The main async function for the keeper service.
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

        logger.info("--- Starting LLM Gateway Keeper (Async) ---")

        # Step 3: Setup Directories.
        _setup_directories(accessor)

        # Step 4: Initialize and Verify Database Connection.
        dsn = accessor.get_database_dsn()
        pool_cfg = accessor.get_pool_config()
        await database.init_db_pool(
            dsn, min_size=pool_cfg.min_size, max_size=pool_cfg.max_size
        )
        db_manager = DatabaseManager(accessor)
        await db_manager.initialize_schema()

        # Step 5: Create Long-Lived Client Factory.
        client_factory = HttpClientFactory(accessor)
        logger.info("Long-lived HttpClientFactory created.")

        # --- Initialize the metrics collector (single-process mode) ---
        _collector = get_collector()
        logger.info("Metrics collector initialized (single-process).")

        # --- Start the /metrics HTTP server as a background task ---
        _metrics_task = asyncio.create_task(_start_metrics_server(logger))

        # --- Start periodic DB metrics collection ---
        _db_metrics_task = asyncio.create_task(
            _collect_db_metrics_loop(db_manager, interval_sec=30)
        )

        # Step 6: Initial Resource Synchronization.
        # This part is now refactored to use the new two-phase cycle function.
        logger.info("Performing initial resource synchronization...")
        await db_manager.providers.sync(
            list(accessor.get_all_providers().keys()), db_manager
        )
        all_syncers = get_all_syncers(accessor, db_manager)
        await run_sync_cycle(accessor, db_manager, all_syncers)
        logger.info("Initial resource synchronization finished.")

        # Step 7: Instantiate Services with Dependencies.
        adaptive_callback = _create_adaptive_metrics_callback()
        all_probes = get_all_probes(
            accessor,
            db_manager,
            client_factory,
            on_batch_complete=adaptive_callback,
        )

        # Step 8: Scheduler Setup.
        scheduler = AsyncIOScheduler(timezone="UTC")

        for i, probe in enumerate(all_probes):
            job_id = f"{probe.__class__.__name__}_cycle_{i}"
            _add_scheduler_job(
                scheduler, probe.run_cycle, "interval", minutes=1, id=job_id
            )

        # REFACTORED: Instead of scheduling each syncer, schedule the central cycle function.
        _add_scheduler_job(
            scheduler,
            run_sync_cycle,
            "interval",
            minutes=5,
            id="two_phase_sync_cycle",
            args=[
                accessor,
                db_manager,
                all_syncers,
            ],  # Pass dependencies to the scheduled job.
        )

        # --- Database maintenance scheduler jobs ---
        # Key purge: weekly cron (Sunday 04:00 UTC).
        _add_scheduler_job(
            scheduler,
            KeyPurger.run_scheduled,
            "cron",
            day_of_week="sun",
            hour=4,
            minute=0,
            id="key_purge",
            args=[accessor, db_manager],
        )

        # Smart vacuum: interval-based, reads interval from config.
        vacuum_interval = accessor.get_database_config().vacuum_policy.interval_minutes
        _add_scheduler_job(
            scheduler,
            DatabaseMaintainer.run_scheduled,
            "interval",
            minutes=vacuum_interval,
            id="smart_vacuum",
            args=[accessor, db_manager],
        )

        # --- Register key export jobs (snapshot + inventory) ---
        exporter = KeyInventoryExporter()
        for provider_name, provider_config in accessor.get_all_providers().items():
            if not provider_config.enabled:
                continue

            key_export = provider_config.key_export

            # Master switch: if disabled, skip all export jobs for this provider.
            if not key_export.enabled:
                continue

            # Snapshot job
            if key_export.snapshot_interval_hours > 0:
                _add_scheduler_job(
                    scheduler,
                    exporter.export_snapshot,
                    trigger=IntervalTrigger(hours=key_export.snapshot_interval_hours),
                    id=f"snapshot_{provider_name}",
                    args=[provider_name, db_manager],
                )

            # Inventory job
            inventory = key_export.inventory
            if inventory.enabled and inventory.statuses:
                _add_scheduler_job(
                    scheduler,
                    exporter.export_inventory,
                    trigger=IntervalTrigger(minutes=inventory.interval_minutes),
                    id=f"inventory_{provider_name}",
                    args=[provider_name, db_manager, inventory.statuses],
                )

        logger.info("Scheduler configured. List of jobs:")
        _ = scheduler.print_jobs()  # pyright: ignore[reportUnknownMemberType]

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
            logger.critical(
                f"A critical error occurred during keeper setup or runtime: {e}",
                exc_info=True,
            )
        else:
            print(
                f"[CRITICAL] A critical error occurred before logging was configured: {e}"
            )
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
        shutdown_logger.info("Keeper has been shut down gracefully.")
