import argparse
import asyncio
import selectors

import uvicorn

from app.authentication.seed import seed_root
from app.config.settings import AUTH_BOOTSTRAP_PASSWORD, AUTH_BOOTSTRAP_USERNAME
from app.runtime.application import Application
from app.runtime.cli import run_cli
from app.runtime.server import create_api
from app.utils.logger import set_log_level


async def main():

    parser = argparse.ArgumentParser()

    parser.add_argument("--api", action="store_true", help="Run FastAPI server")

    parser.add_argument(
        "--log-level",
        default=None,
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        help=(
            "Override the configured log level for this run. "
            "Omit to use LOG_LEVEL from the environment."
        ),
    )

    parser.add_argument(
        "--seed-admin",
        action="store_true",
        help="Reset the root user from AUTH_BOOTSTRAP_* and exit",
    )

    args = parser.parse_args()

    # Highest precedence, and the only lever that works when startup
    # itself is failing and no API is listening yet.
    if args.log_level:
        set_log_level(args.log_level)

    async with Application() as application:
        if args.seed_admin:
            await seed_root(
                application.user_repository,
                username=AUTH_BOOTSTRAP_USERNAME,
                password=AUTH_BOOTSTRAP_PASSWORD,
                force=True,
            )
            return

        if args.api:
            api = create_api(application)

            # uvicorn.run() would start a second event loop, and the
            # connection pool is bound to this one. Serve in place.
            config = uvicorn.Config(
                api,
                host="0.0.0.0",
                port=8000,
                # SSE streams never end on their own — the client stays
                # connected and the generator keeps emitting heartbeats,
                # so graceful shutdown would wait for them forever. Cut
                # whatever is still open after this. Safe here because
                # generation is decoupled from the HTTP request: a stream
                # closed mid-answer costs the client nothing but a
                # reconnect, and the turn finishes regardless.
                timeout_graceful_shutdown=5,
            )

            await uvicorn.Server(config).serve()

        else:
            await run_cli(application)


if __name__ == "__main__":
    try:
        asyncio.run(
            main(),
            loop_factory=lambda: asyncio.SelectorEventLoop(selectors.SelectSelector()),
        )

    except KeyboardInterrupt:
        # A second Ctrl+C during shutdown cancels cleanup on purpose.
        # Nothing is lost: unfinished assistant rows are swept on the next
        # start. Report it rather than printing a stack trace.
        print("Interrupted before shutdown finished.")
