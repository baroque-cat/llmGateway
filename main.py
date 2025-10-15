# main.py

import argparse
import sys

# Add the source directory to the Python path.
# This is a common pattern to ensure that imports work correctly
# when running a script from the project root.
sys.path.insert(0, './src')

from src.services.background_worker import run_worker

def main():
    """
    Main entry point for the LLM Gateway application.
    This script acts as a command-line interface (CLI) to launch
    different services of the application.
    """
    parser = argparse.ArgumentParser(
        description="LLM Gateway - A multi-provider, resilient LLM API gateway."
    )
    
    # Create a subparser to handle different commands (e.g., worker, gateway)
    subparsers = parser.add_subparsers(dest='service', required=True, help='The service to run')

    # --- Command to run the background worker ---
    parser_worker = subparsers.add_parser(
        'worker', 
        help='Run the background worker for health checks, synchronization, and statistics.'
    )
    
    # --- (Placeholder) Command to run the API gateway ---
    # In the future, you will add the gateway service here.
    # parser_gateway = subparsers.add_parser(
    #     'gateway',
    #     help='Run the API gateway server.'
    # )
    # parser_gateway.add_argument('--host', default='127.0.0.1', help='Host to bind the server to.')
    # parser_gateway.add_argument('--port', type=int, default=8000, help='Port to listen on.')

    args = parser.parse_args()

    # Execute the chosen service
    if args.service == 'worker':
        print("Starting the background worker service...")
        run_worker()
    # elif args.service == 'gateway':
    #     print(f"Starting the API gateway on {args.host}:{args.port}...")
    #     # run_gateway(host=args.host, port=args.port) # Future implementation
    else:
        # This case should not be reached due to `required=True` in subparsers,
        # but it's good practice to have a fallback.
        print(f"Error: Unknown service '{args.service}'")
        parser.print_help()
        sys.exit(1)

if __name__ == '__main__':
    main()
