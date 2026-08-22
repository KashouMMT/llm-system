import argparse
import asyncio
import selectors

import uvicorn

from app.runtime.application import Application
from app.runtime.cli import run_cli
from app.runtime.server import create_api
from app.utils.logger import set_log_level


async def main():

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--api", 
        action="store_true", 
        help="Run FastAPI server"
    )

    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        help="Set log Level for logging. Default is INFO",
    )

    args = parser.parse_args()

    set_log_level(args.log_level)

    async with Application() as application:
        if args.api:
            api = create_api(application)

            uvicorn.run(
                api,
                host="0.0.0.0",
                port=8000,
            )
            
        else:
            await run_cli(application)


if __name__ == "__main__":
    asyncio.run(
        main(),
        loop_factory=lambda: asyncio.SelectorEventLoop(selectors.SelectSelector()),
    )
