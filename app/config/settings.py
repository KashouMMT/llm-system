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

# SUMMARY CONFIGURATION
SUMMARY_TOKEN_THRESHOLD = int(os.getenv("SUMMARY_TOKEN_THRESHOLD",1200))
RECENT_MESSAGE_LIMIT = int(os.getenv("RECENT_MESSAGE_LIMIT",20))
MAX_UNSUMMARIZED_MESSAGES = int(os.getenv("MAX_UNSUMMARIZED_MESSAGES",100))
SUMMARY_CHUNK_PROMPT = """
You are a memory compression system.

Extract durable conversation memory.

Rules:
- Extract only information explicitly stated by the user.
- Do not infer facts about the user.
- Do not store assistant assumptions.
- Do not store assistant opinions.
- Ignore fictional roleplay details unless confirmed by the user as real.
- Ignore temporary conversational details.
- Prefer long-term useful information.
- If no information exists for a section, leave it empty.

Return ONLY structured notes.

Format:

TOPICS:
- ...

USER_PREFERENCES:
- ...

USER_GOALS:
- ...

FACTS:
- ...

OPEN_ITEMS:
- ...

Conversation:

{conversation}
""".strip()
SUMMARY_MERGE_PROMPT = """
You are maintaining long-term memory.

Merge CURRENT SUMMARY and NEW SUMMARY.

Rules:
- Keep only useful future context.
- Remove duplicates.
- Preserve user preferences.
- Preserve user goals.
- Preserve durable facts.
- Preserve unresolved issues.
- Remove outdated information.
- Remove filler text.
- Keep the summary concise.
- Output ONLY structured memory notes.

Format:

TOPICS:
- ...

USER_PREFERENCES:
- ...

USER_GOALS:
- ...

FACTS:
- ...

OPEN_ITEMS:
- ...

CURRENT SUMMARY:

{current_summary}

NEW SUMMARY:

{chunk_summary}
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