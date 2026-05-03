# main.py

import asyncio
import logging
import sys

# Add the source directory to the Python path.
# This ensures that imports work correctly when running from the project root.
sys.path.insert(0, "./src")

from src.config import load_config
from src.config.logging_config import setup_logging
from src.core.accessor import ConfigAccessor
from src.services.gateway.gateway_service import create_app
from src.services.keeper import run_keeper

logger = logging.getLogger(__name__)

# === MODULE LEVEL (executed on every import, including uvicorn workers) ===
config = load_config()
accessor = ConfigAccessor(config)
setup_logging(accessor)
app = create_app(accessor)

# === __main__ (local development only) ===
if __name__ == "__main__":
    import uvicorn

    if len(sys.argv) > 1 and sys.argv[1] == "keeper":
        asyncio.run(run_keeper())
    else:
        uvicorn.run(
            app,
            host=config.gateway.host,
            port=config.gateway.port,
            workers=1,
            access_log=False,
        )
