"""Configuration shared by every CLI in the playground.

One place for the facts that used to be copied into each script: where the
project's .env lives, which model to call, and how to build an API client.
Change the model here and every command follows.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI
from vision import DetectionError, build_client

PLAYGROUND_DIR = Path(__file__).resolve().parent
# The repository's own .env, one level up. No separate playground config.
ENV_FILE = PLAYGROUND_DIR.parent / ".env"
DEFAULT_MODEL = "gpt-5.6-luna"


def load_env() -> None:
    """Load the project .env. Call before parsing arguments, since argument
    defaults read environment variables."""
    load_dotenv(ENV_FILE)


def default_model() -> str:
    """$DETECT_MODEL if set, otherwise the project default."""
    return os.getenv("DETECT_MODEL", DEFAULT_MODEL)


def make_client() -> OpenAI:
    """Build the API client from the environment, failing with a readable message."""
    key = os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY")
    if not key:
        raise DetectionError("No API key. Set LLM_API_KEY in the project .env.")
    return build_client(key, os.getenv("LLM_BASE_URL"))
