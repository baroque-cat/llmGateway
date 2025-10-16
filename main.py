# main.py

import argparse
import asyncio
import sys

# Add the source directory to the Python path.
# This ensures that imports work correctly when running from the project root.
sys.path.insert(0, './src')

from src.services.background_worker import run_worker

async def main():
    """
    Main async entry point for the LLM Gateway application.
    This script acts as a command-line interface (CLI) to launch
    different services of the application.
    """
    parser = argparse.ArgumentParser(
        description="LLM Gateway - A multi-provider, resilient LLM API gateway."
    )
    
    subparsers = parser.add_subparsers(dest='service', required=True, help='The service to run')

    # --- Command to run the background worker ---
    parser_worker = subparsers.add_parser(
        'worker', 
        help='Run the background worker for health checks, synchronization, and statistics.'
    )
    
    # --- (Placeholder) Command to run the API gateway ---
    # parser_gateway = subparsers.add_parser(
    #     'gateway',
    #     help='Run the API gateway server.'
    # )
    # parser_gateway.add_argument('--host', default='127.0.0.1', help='Host to bind the server to.')
    # parser_gateway.add_argument('--port', type=int, default=8000, help='Port to listen on.')

    args = parser.parse_args()

    if args.service == 'worker':
        print("Starting the background worker service...")
        await run_worker()
    # elif args.service == 'gateway':
    #     print(f"Starting the API gateway on {args.host}:{args.port}...")
    #     await run_gateway(host=args.host, port=args.port) # Future implementation
    else:
        print(f"Error: Unknown service '{args.service}'")
        parser.print_help()
        sys.exit(1)

if __name__ == '__main__':
    # Run the main async function using asyncio.run()
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nApplication shut down by user.")
