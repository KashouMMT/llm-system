import os
from dotenv import load_dotenv

load_dotenv()

# LLM CONFIGURATION
MODEL_NAME = os.getenv("MODEL_NAME", "dolphin-phi:latest")
TEMPERATURE = float(os.getenv("TEMPERATURE", 0.7))
MAX_TOKENS = int(os.getenv("MAX_TOKENS", 512))
CONTEXT_WINDOW = int(os.getenv("CONTEXT_WINDOW", 4096))
TOP_P = float(os.getenv("TOP_P", 0.9))

# PROMPT
SYSTEM_PROMPT = os.getenv("SYSTEM_PROMPT","default")
DEFAULT_PROMPT = """
You are a helpful, intelligent, and reliable AI assistant.
Provide clear, accurate, and thoughtful responses.
""".strip()

# OTHER CONFIGURATION
LOG_LEVEL = os.getenv("LOG_LEVEL","INFO")
CONSOLE_LOG = os.getenv("CONSOLE_LOG","false")

# POSTGRESQL CONFIGURATION
DB_HOST = os.getenv("DB_HOST","localhost")
DB_PORT = int(os.getenv("DB_PORT",5432))
DB_NAME = os.getenv("DB_NAME","llm_system")
DB_USER = os.getenv("DB_USER","postgres")
DB_PASSWORD = os.getenv("DB_PASSWORD","postgres")