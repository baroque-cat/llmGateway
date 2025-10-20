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

async def main():
    """
    Main async entry point for the LLM Gateway application.
    This script acts as a command-line interface (CLI) to launch
    different services of the application and manage its configuration.
    """
    parser = argparse.ArgumentParser(
        description="LLM Gateway - A multi-provider, resilient LLM API gateway.",
        formatter_class=argparse.RawTextHelpFormatter  # Allows for better formatting in help text
    )
    
    subparsers = parser.add_subparsers(dest='service', required=True, help='The service to run')

    # --- Command to run the background worker ---
    parser_worker = subparsers.add_parser(
        'worker', 
        help='Run the background worker for health checks, synchronization, and statistics.'
    )
    
    # --- Command to manage the configuration ---
    parser_config = subparsers.add_parser(
        'config',
        help='Manage the providers.yaml configuration file.',
        epilog=textwrap.dedent('''
            Examples:
              # Create a single 'gemini' instance named 'gemini-work'
              python main.py config create gemini:gemini-work

              # Create multiple 'gemini' instances and one 'deepseek' instance
              python main.py config create gemini:gemini-personal,gemini-dev deepseek:deepseek-work
              
              # Remove a single instance
              python main.py config remove --provider_name=gemini-work
              
              # Remove multiple instances
              python main.py config remove --provider_name=gemini-personal,deepseek-work
        ''')
    )
    config_subparsers = parser_config.add_subparsers(dest='action', required=True, help='Action to perform on the config')
    
    # --- Sub-command 'config create' ---
    parser_create = config_subparsers.add_parser('create', help='Create new provider instances in the config.')
    parser_create.add_argument(
        'providers', 
        nargs='+', 
        help="Providers to create, in 'type:name1,name2' format."
    )

    # --- Sub-command 'config remove' ---
    parser_remove = config_subparsers.add_parser('remove', help='Remove provider instances from the config.')
    parser_remove.add_argument(
        '--provider_name', 
        required=True, 
        help="Comma-separated list of instance names to remove (e.g., 'gemini-work,deepseek-personal')."
    )

    args = parser.parse_args()

    if args.service == 'worker':
        try:
            print("Starting the background worker service...")
            await run_worker()
        except FileNotFoundError as e:
            # This is a specific catch for when the loader fails to find the config.
            print(f"\n[ERROR] {e}", file=sys.stderr)
            print("Please create a configuration file before running the worker.", file=sys.stderr)
            sys.exit(1)
        except Exception as e:
            # Catch other potential startup errors
            print(f"\n[CRITICAL] A critical error prevented the worker from starting: {e}", file=sys.stderr)
            sys.exit(1)
            
    elif args.service == 'config':
        # The config manager performs synchronous file I/O, so it's not awaited.
        manager = ConfigManager()
        if args.action == 'create':
            manager.create_instances(args.providers)
        elif args.action == 'remove':
            # Split the comma-separated string into a list of names
            names_to_remove = [name.strip() for name in args.provider_name.split(',')]
            manager.remove_instances(names_to_remove)
            
    else:
        print(f"Error: Unknown service '{args.service}'")
        parser.print_help()
        sys.exit(1)

if __name__ == '__main__':
    try:
        # asyncio.run() is suitable for CLI apps that may or may not run async code.
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nApplication shut down by user.")

