# main.py

import argparse
import asyncio
import sys
import textwrap

# Add the source directory to the Python path.
# This ensures that imports work correctly when running from the project root.
sys.path.insert(0, './src')

from src.services.background_worker import run_worker
from src.services.config_manager import ConfigManager
from src.config import load_config  # Import the new centralized config loader

async def main():
    """
    Main async entry point for the LLM Gateway application.
    This script acts as a command-line interface (CLI) to launch
    different services of the application and manage its configuration.
    """
    # Step 2: Set up the main argument parser.
    parser = argparse.ArgumentParser(
        description="LLM Gateway - A multi-provider, resilient LLM API gateway.",
        formatter_class=argparse.RawTextHelpFormatter
    )
    
    subparsers = parser.add_subparsers(dest='service', required=True, help='The service to run')

    # --- Command to run the background worker ---
    parser_worker = subparsers.add_parser(
        'worker', 
        help='Run the background worker for health checks, sync, and stats.'
    )
    
    # --- Command to manage the configuration ---
    # The epilog is updated to reflect the new '--full' flag and remove syntax.
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
    
    # --- Sub-command 'config create' ---
    # This is updated with the '--full' flag as planned in Step 2.
    parser_create = config_subparsers.add_parser('create', help='Create new provider instances.')
    parser_create.add_argument(
        '--full',
        action='store_true',
        help="Create full provider configurations with all default fields written to the file."
    )
    parser_create.add_argument(
        'providers', 
        nargs='+', 
        help="Providers to create, in 'type:name1,name2' format."
    )

    # --- Sub-command 'config remove' ---
    # The help text is updated to clarify the new consistent syntax.
    parser_remove = config_subparsers.add_parser('remove', help='Remove provider instances.')
    parser_remove.add_argument(
        'providers', 
        nargs='+',
        help="Providers to remove, in 'type:name1,name2' format."
    )
    
    # --- Sub-command 'config list' ---
    config_subparsers.add_parser('list', help='List all configured provider instances.')


    args = parser.parse_args()

    # Step 3: Implement the main application logic based on parsed arguments.
    if args.service == 'worker':
        try:
            print("Initializing configuration...")
            # Use the new centralized loader to initialize the global config instance.
            # This is a key improvement from the plan.
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
            
    elif args.service == 'config':
        manager = ConfigManager()
        try:
            if args.action == 'create':
                # Pass the 'full' flag directly to the manager.
                manager.create_instances(args.providers, full=args.full)
            elif args.action == 'remove':
                # The logic is simplified; the manager now handles the full argument string.
                manager.remove_instances(args.providers)
            elif args.action == 'list':
                manager.list_instances()
        except ValueError as e:
            # Catch potential errors from ConfigManager and display them cleanly.
            # This handles a potential error scenario from the plan.
            print(f"[ERROR] {e}", file=sys.stderr)
            sys.exit(1)
            
    else:
        # This case should not be reachable due to 'required=True' but is good practice.
        print(f"Error: Unknown service '{args.service}'")
        parser.print_help()
        sys.exit(1)

# Step 4: Standard entry point for the async application.
if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nApplication shut down by user.")

