import os
from dotenv import load_dotenv

load_dotenv()

MODEL_NAME = os.getenv("MODEL_NAME", "dolphin-phi:latest")
TEMPERATURE = float(os.getenv("TEMPERATURE", 0.7))

CHARACTER = os.getenv("CHARACTER")

LOG_LEVEL = os.getenv("LOG_LEVEL","INFO")
CONSOLE_LOG = os.getenv("CONSOLE_LOG","false")

MAX_TOKENS = int(os.getenv("MAX_TOKENS", 512))
CONTEXT_WINDOW = int(os.getenv("CONTEXT_WINDOW", 4096))
TOP_P = float(os.getenv("TOP_P", 0.9))

DEFAULT_SYSTEM_PROMPT = """
You are a helpful, intelligent, and reliable AI assistant.
Provide clear, accurate, and thoughtful responses.
""".strip()

