import argparse
import asyncio

import uvicorn

from app.runtime.application import create_application
from app.runtime.cli import run_cli
from app.runtime.server import create_api
from app.utils.logger import set_log_level

def main():
    
    parser = argparse.ArgumentParser()
    
    parser.add_argument(
        "--api",
        action="store_true",
        help="Run FastAPI server"
    )
    
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable Debug Logging"
    )
    
    args = parser.parse_args()
    
    if args.debug:
        set_log_level("DEBUG")
    else:
        set_log_level("INFO")
    
    application = create_application()
    
    if args.api:
        api = create_api(application)
        uvicorn.run(
            api,
            host="0.0.0.0",
            port=8000
        )
    else:
        asyncio.run(
            run_cli(application)
        )

if __name__ == "__main__":
    main()