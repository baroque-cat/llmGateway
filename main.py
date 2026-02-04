# main.py

import argparse
import asyncio
import sys

# Add the source directory to the Python path.
# This ensures that imports work correctly when running from the project root.
sys.path.insert(0, "./src")

# --- Imports for both Gateway and Worker Services ---
import uvicorn
from src.services.gateway_service import create_app
from src.core.accessor import ConfigAccessor
from src.config.logging_config import setup_logging
from src.services.background_worker import run_worker
from src.config import load_config

# --- REFACTORED: Service starter functions ---


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

        # Setup logging first, so other components can log during init.
        setup_logging(accessor)

        # --- FIXED: Service component initialization is now moved into the
        # FastAPI startup event to ensure they are created within the correct
        # asyncio event loop and after the database pool is ready.

        # Create the FastAPI app instance using the factory.
        # We only pass the accessor, as the app will manage its own lifecycle.
        app = create_app(accessor=accessor)

        print(
            f"Starting API Gateway on {args.host}:{args.port} with {args.workers} worker(s)..."
        )

        # This is a blocking call that starts the Uvicorn server.
        uvicorn.run(app, host=args.host, port=args.port, workers=args.workers)

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


async def _start_worker_service():
    """
    Initializes and starts the background worker service.
    This function is asynchronous as the worker is a pure asyncio application.
    """
    try:
        print("Initializing configuration...")
        load_config()
        print("Starting the background worker service...")
        await run_worker()
    except FileNotFoundError as e:
        print(f"\n[ERROR] {e}", file=sys.stderr)
        print(
            "Please create a configuration file before running the worker.",
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
            f"\n[CRITICAL] A critical error prevented the worker from starting: {e}",
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

    # --- Command to run the background worker ---
    subparsers.add_parser(
        "worker", help="Run the background worker for health checks, sync, and stats."
    )

    # --- Command to run the API Gateway ---
    parser_gateway = subparsers.add_parser(
        "gateway", help="Run the FastAPI API Gateway service."
    )
    parser_gateway.add_argument(
        "--host",
        type=str,
        default="0.0.0.0",
        help="The host to bind the server to. Default: 0.0.0.0",
    )
    parser_gateway.add_argument(
        "--port",
        type=int,
        default=8000,
        help="The port to bind the server to. Default: 8000",
    )
    parser_gateway.add_argument(
        "--workers",
        type=int,
        default=1,
        help="The number of worker processes for Uvicorn. Default: 1",
    )

    args = parser.parse_args()

    # --- Main Application Logic (Dispatcher) ---
    if args.service == "worker":
        asyncio.run(_start_worker_service())

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
