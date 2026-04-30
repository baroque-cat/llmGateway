# main.py

import argparse
import asyncio
import logging
import sys

# Add the source directory to the Python path.
# This ensures that imports work correctly when running from the project root.
sys.path.insert(0, "./src")

# --- Imports for both Gateway and Worker Services ---
import uvicorn

from src.config import load_config
from src.config.logging_config import setup_logging
from src.config.schemas import Config
from src.core.accessor import ConfigAccessor
from src.services.gateway.gateway_service import create_app
from src.services.keeper import run_keeper

logger = logging.getLogger(__name__)

# --- REFACTORED: Service starter functions ---


def validate_pool_sizing(config: Config) -> None:
    """
    Pre-startup check of total connection pool sizing.

    Computes ``worst_case = (gateway_workers + 1) × pool_max_size``
    and compares with the PostgreSQL limit (97 user connections out of 100,
    minus 3 superuser-reserved).

    - ``worst_case > 97`` → CRITICAL (guaranteed failure with default settings)
    - ``worst_case > 77`` (80% of 97) → WARNING
    - Otherwise → no messages

    This function does not block startup — it only logs warnings.
    """
    pool_max = config.database.pool.max_size
    gw_workers = config.gateway.workers
    processes = gw_workers + 1  # +1 for the Keeper
    worst_case = processes * pool_max
    pg_limit = 97  # 100 - 3 superuser reserve

    if worst_case > pg_limit:
        logger.critical(
            f"CONNECTION OVERFLOW! {processes} processes × pool.max_size={pool_max} "
            f"= {worst_case} connections, exceeds PostgreSQL limit ({pg_limit}). "
            f"Reduce gateway.workers or database.pool.max_size."
        )
    elif worst_case > int(pg_limit * 0.8):
        logger.warning(
            f"Pool sizing is aggressive: {processes} processes × pool.max_size={pool_max} "
            f"= {worst_case} connections ({worst_case * 100 // pg_limit}% of {pg_limit}). "
            f"Consider reducing gateway.workers or database.pool.max_size."
        )


def _start_gateway_service(args: argparse.Namespace):
    """
    Initializes and starts the API Gateway service.
    This function is synchronous because uvicorn.run() is a blocking call
    that manages its own asyncio event loop.
    """
    try:
        print("Initializing configuration...")
        config = load_config()
        accessor = ConfigAccessor(config)

        # CLI-override: apply only if explicitly passed (sentinel None).
        if args.host is not None:
            config.gateway.host = args.host
        if args.port is not None:
            config.gateway.port = args.port
        if args.workers is not None:
            config.gateway.workers = args.workers

        # Pre-startup pool sizing validation.
        validate_pool_sizing(config)

        # Setup logging first, so other components can log during init.
        setup_logging(accessor)

        # --- FIXED: Service component initialization is now moved into the
        # FastAPI startup event to ensure they are created within the correct
        # asyncio event loop and after the database pool is ready.

        # Create the FastAPI app instance using the factory.
        # We only pass the accessor, as the app will manage its own lifecycle.
        app = create_app(accessor=accessor)

        workers = config.gateway.workers
        if workers > 1:
            print(
                "WARNING: workers > 1 requires an import string ('module:app'). "
                "uvicorn.run() received a direct app object — falling back to 1 worker. "
                "In containers, scale via replicas (docker-compose up --scale gateway=N), "
                "not uvicorn workers."
            )
            workers = 1

        print(
            f"Starting API Gateway on {config.gateway.host}:{config.gateway.port} "
            f"with {workers} worker(s)..."
        )

        # This is a blocking call that starts the Uvicorn server.
        uvicorn.run(
            app,
            host=config.gateway.host,
            port=config.gateway.port,
            workers=workers,
            access_log=False,
        )

    except FileNotFoundError as e:
        print(f"\n[ERROR] {e}", file=sys.stderr)
        print(
            "Please create a configuration file before running the gateway.",
            file=sys.stderr,
        )
        sys.exit(1)
    except (ValueError, TypeError) as e:
        print(f"\n[CRITICAL] Configuration validation failed: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(
            f"\n[CRITICAL] A critical error prevented the gateway from starting: {e}",
            file=sys.stderr,
        )
        sys.exit(1)


async def _start_keeper_service():
    """
    Initializes and starts the keeper service.
    This function is asynchronous as the keeper is a pure asyncio application.
    """
    try:
        print("Initializing configuration...")
        config = load_config()

        # Pre-startup pool sizing validation.
        validate_pool_sizing(config)

        print("Starting the keeper service...")
        await run_keeper()
    except FileNotFoundError as e:
        print(f"\n[ERROR] {e}", file=sys.stderr)
        print(
            "Please create a configuration file before running the keeper.",
            file=sys.stderr,
        )
        print(
            "Example: cp examples/full_config.yaml config/providers.yaml",
            file=sys.stderr,
        )
        sys.exit(1)
    except (ValueError, TypeError) as e:
        print(f"\n[CRITICAL] Configuration validation failed: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(
            f"\n[CRITICAL] A critical error prevented the keeper from starting: {e}",
            file=sys.stderr,
        )
        sys.exit(1)


# --- REFACTORED: Main entry point is now synchronous ---
def main():
    """
    Main entry point for the LLM Gateway application CLI.
    This function is now synchronous and acts as a dispatcher.
    """
    parser = argparse.ArgumentParser(
        description="LLM Gateway - A multi-provider, resilient LLM API gateway.",
        formatter_class=argparse.RawTextHelpFormatter,
    )

    subparsers = parser.add_subparsers(
        dest="service", required=True, help="The service to run"
    )

    # --- Command to run the keeper ---
    subparsers.add_parser(
        "keeper", help="Run the keeper for health checks, sync, and stats."
    )

    # --- Command to run the API Gateway ---
    parser_gateway = subparsers.add_parser(
        "gateway", help="Run the FastAPI API Gateway service."
    )
    parser_gateway.add_argument(
        "--host",
        type=str,
        default=None,
        help="The host to bind the server to. Default: from config (0.0.0.0)",
    )
    parser_gateway.add_argument(
        "--port",
        type=int,
        default=None,
        help="The port to bind the server to. Default: from config (55300)",
    )
    parser_gateway.add_argument(
        "--workers",
        type=int,
        default=None,
        help="The number of worker processes for Uvicorn. Default: from config (4)",
    )

    args = parser.parse_args()

    # --- Main Application Logic (Dispatcher) ---
    if args.service == "keeper":
        asyncio.run(_start_keeper_service())

    elif args.service == "gateway":
        _start_gateway_service(args)

    else:
        print(f"Error: Unknown service '{args.service}'")
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    try:
        # Call the synchronous main function directly.
        main()
    except KeyboardInterrupt:
        print("\nApplication shut down by user.")
