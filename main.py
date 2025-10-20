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
              # List all configured instances
              python main.py config list

              # Create a single 'gemini' instance named 'gemini-work'
              python main.py config create gemini:gemini-work

              # Create multiple instances at once
              python main.py config create gemini:gemini-personal,gemini-dev deepseek:deepseek-work
              
              # Remove one or more instances
              python main.py config remove gemini:gemini-work deepseek:deepseek-work
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
        'providers', 
        nargs='+',
        help="Providers to remove, in 'type:name1,name2' format for consistency."
    )
    
    # --- Sub-command 'config list' (NEW) ---
    config_subparsers.add_parser('list', help='List all configured provider instances.')


    args = parser.parse_args()

    if args.service == 'worker':
        try:
            print("Starting the background worker service...")
            await run_worker()
        except FileNotFoundError as e:
            print(f"\n[ERROR] {e}", file=sys.stderr)
            print("Please create a configuration file before running the worker.", file=sys.stderr)
            sys.exit(1)
        except Exception as e:
            print(f"\n[CRITICAL] A critical error prevented the worker from starting: {e}", file=sys.stderr)
            sys.exit(1)
            
    elif args.service == 'config':
        manager = ConfigManager()
        if args.action == 'create':
            manager.create_instances(args.providers)
        elif args.action == 'remove':
            all_names_to_remove = []
            try:
                for arg in args.providers:
                    _provider_type, instance_names = manager._parse_provider_arg(arg)
                    all_names_to_remove.extend(instance_names)
                manager.remove_instances(all_names_to_remove)
            except ValueError as e:
                print(f"Error: {e}", file=sys.stderr)
                sys.exit(1)
        elif args.action == 'list':
            manager.list_instances()
            
    else:
        print(f"Error: Unknown service '{args.service}'")
        parser.print_help()
        sys.exit(1)

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nApplication shut down by user.")

