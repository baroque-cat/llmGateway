# main.py

import argparse
import asyncio
import sys
import textwrap

# Add the source directory to the Python path.
# This ensures that imports work correctly when running from the project root.
sys.path.insert(0, './src')

# --- Imports for both Gateway and Worker Services ---
import uvicorn
from src.services.gateway_service import create_app
from src.core.accessor import ConfigAccessor
from src.config.logging_config import setup_logging
from src.services.background_worker import run_worker
from src.services.config_manager import ConfigManager
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
        
        print(f"Starting API Gateway on {args.host}:{args.port} with {args.workers} worker(s)...")
        
        # This is a blocking call that starts the Uvicorn server.
        uvicorn.run(
            app,
            host=args.host,
            port=args.port,
            workers=args.workers
        )
            
    except FileNotFoundError as e:
        print(f"\n[ERROR] {e}", file=sys.stderr)
        print("Please create a configuration file before running the gateway.", file=sys.stderr)
        sys.exit(1)
    except (ValueError, TypeError) as e:
        print(f"\n[CRITICAL] Configuration validation failed: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"\n[CRITICAL] A critical error prevented the gateway from starting: {e}", file=sys.stderr)
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
        print("Please create a configuration file before running the worker.", file=sys.stderr)
        print("Example: python main.py config create gemini:my-first-instance", file=sys.stderr)
        sys.exit(1)
    except (ValueError, TypeError) as e:
        print(f"\n[CRITICAL] Configuration validation failed: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"\n[CRITICAL] A critical error prevented the worker from starting: {e}", file=sys.stderr)
        sys.exit(1)


# --- REFACTORED: Main entry point is now synchronous ---
def main():
    """
    Main entry point for the LLM Gateway application CLI.
    This function is now synchronous and acts as a dispatcher.
    """
    parser = argparse.ArgumentParser(
        description="LLM Gateway - A multi-provider, resilient LLM API gateway.",
        formatter_class=argparse.RawTextHelpFormatter
    )
    
    subparsers = parser.add_subparsers(dest='service', required=True, help='The service to run')

    # --- Command to run the background worker ---
    subparsers.add_parser(
        'worker', 
        help='Run the background worker for health checks, sync, and stats.'
    )
    
    # --- Command to run the API Gateway ---
    parser_gateway = subparsers.add_parser(
        'gateway',
        help='Run the FastAPI API Gateway service.'
    )
    parser_gateway.add_argument(
        '--host', type=str, default='0.0.0.0',
        help="The host to bind the server to. Default: 0.0.0.0"
    )
    parser_gateway.add_argument(
        '--port', type=int, default=8000,
        help="The port to bind the server to. Default: 8000"
    )
    parser_gateway.add_argument(
        '--workers', type=int, default=1,
        help="The number of worker processes for Uvicorn. Default: 1"
    )
    
    # --- Command to manage the configuration ---
    parser_config = subparsers.add_parser(
        'config',
        help='Manage the providers.yaml configuration file.',
        epilog=textwrap.dedent('''
            Examples:
              # List all configured instances
              python main.py config list

              # Create a minimal 'gemini' instance named 'gemini-work'
              python main.py config create gemini:gemini-work

              # Create a FULL instance with all default fields explicit
              python main.py config create --full gemini:gemini-pro-setup

              # Create multiple instances at once
              python main.py config create gemini:gemini-dev,gemini-test deepseek:deepseek-work
              
              # Remove one or more instances (using the same 'type:name' syntax)
              python main.py config remove gemini:gemini-work deepseek:deepseek-work
        ''')
    )
    config_subparsers = parser_config.add_subparsers(dest='action', required=True, help='Action to perform on the config')
    
    parser_create = config_subparsers.add_parser('create', help='Create new provider instances.')
    parser_create.add_argument(
        '--full', action='store_true',
        help="Create full provider configurations with all default fields written to the file."
    )
    parser_create.add_argument(
        'providers', nargs='+', 
        help="Providers to create, in 'type:name1,name2' format."
    )

    parser_remove = config_subparsers.add_parser('remove', help='Remove provider instances.')
    parser_remove.add_argument(
        'providers', nargs='+',
        help="Providers to remove, in 'type:name1,name2' format."
    )
    
    config_subparsers.add_parser('list', help='List all configured provider instances.')

    args = parser.parse_args()

    # --- Main Application Logic (Dispatcher) ---
    if args.service == 'worker':
        asyncio.run(_start_worker_service())
            
    elif args.service == 'gateway':
        _start_gateway_service(args)
    
    elif args.service == 'config':
        manager = ConfigManager()
        try:
            if args.action == 'create':
                manager.create_instances(args.providers, full=args.full)
            elif args.action == 'remove':
                manager.remove_instances(args.providers)
            elif args.action == 'list':
                manager.list_instances()
        except ValueError as e:
            print(f"[ERROR] {e}", file=sys.stderr)
            sys.exit(1)
            
    else:
        print(f"Error: Unknown service '{args.service}'")
        parser.print_help()
        sys.exit(1)

if __name__ == '__main__':
    try:
        # Call the synchronous main function directly.
        main()
    except KeyboardInterrupt:
        print("\nApplication shut down by user.")

