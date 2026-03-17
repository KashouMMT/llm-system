from langchain_core.chat_history import InMemoryChatMessageHistory
from app.utils.logger import logger

class ShortTermMemory:
    def __init__(self):
        self.store = {}
        
    def get_history(self, session_id: str):
        
        logger.debug(f"ShortTermMemory accessed | session={session_id}")
        
        if session_id not in self.store:
            logger.debug(f"Creating new short-term memory session | {session_id}")
            self.store[session_id] = InMemoryChatMessageHistory()
            
        return self.store[session_id]